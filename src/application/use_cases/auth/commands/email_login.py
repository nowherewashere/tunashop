import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from src.application.common import Interactor, TurnstileVerifier
from src.application.common.dao import EmailLoginLinkDao, RateLimiter, UserDao
from src.application.common.email_sender import EmailSender
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.use_cases.auth._codes import (
    check_email_resend_cooldown,
    generate_email_verification_code,
    hash_email_verification_code,
)
from src.application.use_cases.user.commands.web_registration import (
    RegisterWebUser,
    RegisterWebUserDto,
)
from src.core.config import AppConfig
from src.core.constants import (
    EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS,
    TIME_1M,
)
from src.core.email_templates import render_login_code_email
from src.core.enums import AuthType
from src.core.exceptions import EmailDeliveryDisabledError
from src.core.utils.time import datetime_now


@dataclass
class RequestEmailLoginCodeDto:
    email: str
    referral_code: Optional[str] = None
    ip: Optional[str] = None
    turnstile_token: Optional[str] = None


@dataclass
class EmailLoginCodeRequested:
    target_email: str
    expires_at: datetime


class RequestEmailLoginCode(Interactor[RequestEmailLoginCodeDto, EmailLoginCodeRequested]):
    """Passwordless login step 1: send a one-time code to an email.

    Find-or-create the user by email (silent registration for a new email), then send a
    verification code that ``VerifyEmailLoginCode`` consumes to issue a session. Reuses the
    ``email_verification_code_hash``/``email_verification_expires_at`` columns.

    NOTE: this endpoint is anonymous and creates a user row for an unseen email, so it MUST be
    fronted by rate-limiting (email+IP+global) and a captcha (Cloudflare Turnstile) to prevent
    account farming and email bombing — see the website-backend spec §9.3. The per-email resend
    cooldown below only throttles repeat requests for an already-seen email. The captcha is the
    only gate that does not depend on the client IP being attributable, so the global cap is what
    still holds if IP attribution is ever wrong.
    """

    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        email_sender: EmailSender,
        register_web_user: RegisterWebUser,
        rate_limiter: RateLimiter,
        turnstile: TurnstileVerifier,
        email_login_link: EmailLoginLinkDao,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.email_sender = email_sender
        self.register_web_user = register_web_user
        self.rate_limiter = rate_limiter
        self.turnstile = turnstile
        self.email_login_link = email_login_link

    async def _execute(
        self, actor: UserDto, data: RequestEmailLoginCodeDto
    ) -> EmailLoginCodeRequested:
        if self.turnstile.is_enabled and not await self.turnstile.verify(
            data.turnstile_token or "", data.ip
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Captcha verification failed",
            )

        if not self.email_sender.is_enabled:
            raise EmailDeliveryDisabledError("Email delivery is not configured")

        await self._enforce_rate_limits(data)

        ttl_minutes = self.config.email.verification_code_ttl_minutes
        user = await self.user_dao.get_by_email(data.email)

        if user is not None:
            check_email_resend_cooldown(
                user.email_verification_expires_at,
                ttl_minutes,
                EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS,
                datetime_now(),
            )

        code = generate_email_verification_code()
        expires_at = datetime_now() + timedelta(minutes=ttl_minutes)
        code_hash = hash_email_verification_code(code, self.config.crypt_key.get_secret_value())

        # One-tap alternative to typing the code. Stored before the send so a link that
        # reaches an inbox is always live; an unused token just expires with the code.
        # Skipped when no site URL is configured — then the email carries only the code.
        link_url = None
        site_url = self.config.web_cabinet_url.rstrip("/")
        if site_url:
            link_token = secrets.token_urlsafe(32)
            await self.email_login_link.put(link_token, data.email, ttl=ttl_minutes * TIME_1M)
            link_url = f"{site_url}/login/link?t={link_token}"

        message = render_login_code_email(
            code=code, minutes=ttl_minutes, link_url=link_url, site_url=site_url
        )

        # Send first; persist/create only on successful delivery so a failed send does not
        # leave a started cooldown or a phantom account (mirrors RequestEmailVerification).
        await self.email_sender.send(
            to=data.email,
            subject=message.subject,
            body=message.text,
            html=message.html,
        )

        if user is None:
            await self._create_user(data, code_hash, expires_at)
        else:
            user.email_verification_code_hash = code_hash
            user.email_verification_expires_at = expires_at
            async with self.uow:
                updated = await self.user_dao.update(user)
                if not updated:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found during login code request",
                    )
                await self.uow.commit()

        return EmailLoginCodeRequested(target_email=data.email, expires_at=expires_at)

    async def _enforce_rate_limits(self, data: RequestEmailLoginCodeDto) -> None:
        too_many = HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many code requests. Please try again later.",
        )
        email_cfg = self.config.email
        if data.ip and not await self.rate_limiter.hit(
            "otp_ip",
            data.ip,
            limit=email_cfg.code_max_per_ip,
            window_seconds=email_cfg.code_rate_window_seconds,
        ):
            raise too_many
        if not await self.rate_limiter.hit(
            "otp_email",
            data.email,
            limit=email_cfg.code_max_per_email,
            window_seconds=email_cfg.code_rate_window_seconds,
        ):
            raise too_many
        # Checked last, so a single abusive email/IP is rejected above without
        # spending the shared budget that keeps everyone else able to log in.
        if not await self.rate_limiter.hit(
            "otp_global",
            "all",
            limit=email_cfg.code_max_global,
            window_seconds=email_cfg.code_rate_window_seconds,
        ):
            raise too_many

    async def _create_user(
        self, data: RequestEmailLoginCodeDto, code_hash: str, expires_at: datetime
    ) -> UserDto:
        referral_code = data.referral_code
        if referral_code and not await self.user_dao.get_by_referral_code(referral_code):
            referral_code = None

        new_user = UserDto(
            telegram_id=None,
            auth_type=AuthType.EMAIL,
            email=data.email,
            password_hash=None,
            username=None,
            name=data.email.split("@")[0],
            language=self.config.default_locale,
            email_verification_code_hash=code_hash,
            email_verification_expires_at=expires_at,
        )
        try:
            return await self.register_web_user.system(
                RegisterWebUserDto(user=new_user, referral_code=referral_code)
            )
        except IntegrityError as e:
            existing = await self.user_dao.get_by_email(data.email)
            if existing:
                return existing
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="User creation conflict"
            ) from e


@dataclass
class VerifyEmailLoginLinkDto:
    token: str


class VerifyEmailLoginLink(Interactor[VerifyEmailLoginLinkDto, UserDto]):
    """Consume a mailed one-tap sign-in link.

    The link is a bearer credential — anyone holding it is treated as the address's
    owner, exactly like the code — so it is single-use, expires with the code, and is
    stored only as a hash.

    It is deliberately consumed by a POST the user triggers on a confirmation page, not
    by opening the link: corporate mail scanners and link-preview crawlers follow URLs
    in email, and a GET that signed the user in would be burned before they ever
    clicked. That page is the only reason this flow is safe to mail at all.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        email_login_link: EmailLoginLinkDao,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.email_login_link = email_login_link

    async def _execute(self, actor: UserDto, data: VerifyEmailLoginLinkDto) -> UserDto:
        invalid = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired link"
        )
        email = await self.email_login_link.consume(data.token)
        if not email:
            raise invalid

        user = await self.user_dao.get_by_email(email)
        if user is None:
            raise invalid
        if user.is_blocked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")

        # Delivery to that address is the proof of ownership, same as the code path —
        # and the pending code is dropped so one request cannot be used twice.
        user.is_email_verified = True
        user.email_verification_code_hash = None
        user.email_verification_expires_at = None

        async with self.uow:
            updated = await self.user_dao.update(user)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during link login",
                )
            await self.uow.commit()
        return updated


@dataclass
class VerifyEmailLoginCodeDto:
    email: str
    code: str


class VerifyEmailLoginCode(Interactor[VerifyEmailLoginCodeDto, UserDto]):
    """Passwordless login step 2: verify the code and return the user for session issuance.

    On success the email is marked verified (the code proves ownership) and the code is cleared.
    Errors are intentionally generic to avoid email enumeration.

    NOTE: a 6-digit code within the TTL is brute-forceable without attempt limiting; verify calls
    MUST be rate-limited (email+IP) alongside request-code — see the website-backend spec §9.3.
    """

    required_permission = None

    def __init__(self, config: AppConfig, uow: UnitOfWork, user_dao: UserDao) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: VerifyEmailLoginCodeDto) -> UserDto:
        user = await self.user_dao.get_by_email(data.email)
        if (
            user is None
            or not user.email_verification_code_hash
            or not user.email_verification_expires_at
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code"
            )

        if user.email_verification_expires_at < datetime_now():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Code has expired")

        incoming_hash = hash_email_verification_code(
            data.code, self.config.crypt_key.get_secret_value()
        )
        if not hmac.compare_digest(incoming_hash, user.email_verification_code_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

        if user.is_blocked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")

        user.is_email_verified = True
        user.email_verification_code_hash = None
        user.email_verification_expires_at = None

        async with self.uow:
            updated = await self.user_dao.update(user)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during login code verification",
                )
            await self.uow.commit()
        return updated
