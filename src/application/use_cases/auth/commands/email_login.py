import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from src.application.common import Interactor
from src.application.common.dao import RateLimiter, UserDao
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
    EMAIL_CODE_MAX_PER_EMAIL,
    EMAIL_CODE_MAX_PER_IP,
    EMAIL_CODE_RATE_WINDOW_SECONDS,
    EMAIL_VERIFICATION_BODY_TEMPLATE,
    EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS,
    EMAIL_VERIFICATION_SUBJECT,
)
from src.core.enums import AuthType
from src.core.exceptions import EmailDeliveryDisabledError
from src.core.utils.time import datetime_now


@dataclass
class RequestEmailLoginCodeDto:
    email: str
    referral_code: Optional[str] = None
    ip: Optional[str] = None


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
    fronted by rate-limiting (email+IP) and a captcha (Cloudflare Turnstile) to prevent account
    farming and email bombing — see the website-backend spec §9.3. The per-email resend cooldown
    below only throttles repeat requests for an already-seen email.
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
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.email_sender = email_sender
        self.register_web_user = register_web_user
        self.rate_limiter = rate_limiter

    async def _execute(
        self, actor: UserDto, data: RequestEmailLoginCodeDto
    ) -> EmailLoginCodeRequested:
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

        # Send first; persist/create only on successful delivery so a failed send does not
        # leave a started cooldown or a phantom account (mirrors RequestEmailVerification).
        await self.email_sender.send(
            to=data.email,
            subject=EMAIL_VERIFICATION_SUBJECT,
            body=EMAIL_VERIFICATION_BODY_TEMPLATE.format(code=code, minutes=ttl_minutes),
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
        if data.ip and not await self.rate_limiter.hit(
            "otp_ip",
            data.ip,
            limit=EMAIL_CODE_MAX_PER_IP,
            window_seconds=EMAIL_CODE_RATE_WINDOW_SECONDS,
        ):
            raise too_many
        if not await self.rate_limiter.hit(
            "otp_email",
            data.email,
            limit=EMAIL_CODE_MAX_PER_EMAIL,
            window_seconds=EMAIL_CODE_RATE_WINDOW_SECONDS,
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
