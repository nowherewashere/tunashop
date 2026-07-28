import hmac
from typing import Final, Optional, Sequence
from urllib.parse import urlencode

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from loguru import logger

from src.application.common.dao import (
    BotLoginDao,
    RateLimiter,
    UserDao,
    UserOAuthProviderDao,
)
from src.application.common.dao.auth import AuthSessionDao
from src.application.common.dao.oauth_state import OAuthFlowMode, OAuthFlowState, OAuthStateDao
from src.application.dto import UserDto
from src.application.dto.user import UserOAuthProviderDto
from src.application.use_cases.auth.commands.bot_login import (
    ClaimBotLogin,
    ClaimBotLoginDto,
    StartBotLogin,
    StartBotLoginDto,
)
from src.application.use_cases.auth.commands.email import (
    ChangeEmail,
    ChangeEmailDto,
    ConfirmEmailVerification,
    ConfirmEmailVerificationDto,
    RequestEmailVerification,
    RequestEmailVerificationDto,
)
from src.application.use_cases.auth.commands.email_login import (
    RequestEmailLoginCode,
    RequestEmailLoginCodeDto,
    VerifyEmailLoginCode,
    VerifyEmailLoginCodeDto,
    VerifyEmailLoginLink,
    VerifyEmailLoginLinkDto,
)
from src.application.use_cases.auth.commands.login import LoginEmailUser, LoginEmailUserDto
from src.application.use_cases.auth.commands.oauth import (
    AuthenticateOAuth,
    AuthenticateOAuthDto,
    LinkOAuthProvider,
    LinkOAuthProviderDto,
    OAuthFlowStarted,
    StartOAuth,
    StartOAuthDto,
    UnlinkOAuthProvider,
    UnlinkOAuthProviderDto,
    hash_binding,
)
from src.application.use_cases.auth.commands.password import ChangePassword, ChangePasswordDto
from src.application.use_cases.auth.commands.register import (
    RegisterEmailUser,
    RegisterEmailUserDto,
)
from src.application.use_cases.auth.commands.session import RefreshSession, RefreshSessionDto
from src.application.use_cases.auth.commands.telegram import (
    AuthenticateTelegram,
    AuthenticateTelegramWebApp,
    LinkTelegram,
    LinkTelegramData,
    TelegramAuthData,
)
from src.core.config import AppConfig
from src.core.constants import API_V1
from src.core.enums import OAuthProvider
from src.core.exceptions import (
    EmailDeliveryDisabledError,
    EmailDeliveryError,
    OAuthExchangeError,
)
from src.web.schemas import (
    AuthResponse,
    BotLoginClaimRequest,
    BotLoginStartResponse,
    BotLoginStatusResponse,
    ChangeEmailRequest,
    ChangeEmailResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ConfirmEmailVerificationRequest,
    ConfirmEmailVerificationResponse,
    LoginRequest,
    LogoutResponse,
    MeResponse,
    OAuthProviderInfoResponse,
    RegisterRequest,
    RequestEmailLoginCodeRequest,
    RequestEmailLoginCodeResponse,
    RequestEmailVerificationCodeRequest,
    RequestEmailVerificationCodeResponse,
    TelegramAuthRequest,
    TelegramLinkResponse,
    TelegramWebAppAuthRequest,
    VerifyEmailLoginCodeRequest,
    VerifyEmailLoginLinkRequest,
)

from ._common import (
    CurrentUser,
    clear_auth_cookies,
    get_client_ip,
    issue_session,
    set_auth_cookies,
)

router = APIRouter(prefix="/auth", tags=["Public - Auth"])

# Scoped to the OAuth routes so the binding cookie is not attached to every API call.
_BINDING_COOKIE = "oauth_binding"
_BINDING_COOKIE_PATH: Final[str] = API_V1 + "/public/auth/oauth"

# Same idea for the bot-confirmed sign-in: proves the claim comes from the browser
# that started the flow, so a token read off someone's screen is not enough.
_BOT_LOGIN_COOKIE = "bot_login_binding"
_BOT_LOGIN_COOKIE_PATH: Final[str] = API_V1 + "/public/auth/telegram/bot-login"

# Application-level failures we are willing to name to the browser. A closed
# allowlist, never a passthrough: the callback answers with a redirect, and anything
# echoed into that URL lands in history and in the SPA's hands.
_DETAIL_TO_CODE: Final[dict[str, str]] = {
    "oauth_email_unverified": "email_unverified",
    "already_linked_other": "already_linked_other",
    "two_active_subscriptions": "two_active_subscriptions",
    "two_telegram_accounts": "two_telegram_accounts",
    "last_sign_in_method": "last_sign_in_method",
    "account_blocked": "blocked",
    "User is blocked": "blocked",
}
_STATUS_TO_CODE: Final[dict[int, str]] = {
    status.HTTP_403_FORBIDDEN: "blocked",
    status.HTTP_404_NOT_FOUND: "disabled",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
}
# The provider's own `error` values. Everything outside this map collapses to
# provider_error; `error_description` is logged and never travels in the URL.
_PROVIDER_ERROR_TO_CODE: Final[dict[str, str]] = {
    "access_denied": "access_denied",
}


def _to_me_response(
    user: UserDto,
    providers: Sequence[UserOAuthProviderDto] = (),
) -> MeResponse:
    return MeResponse(
        telegram_id=user.telegram_id,
        auth_type=user.auth_type,
        email=user.email,
        is_email_verified=user.is_email_verified,
        pending_email=user.pending_email,
        name=user.name,
        username=user.username,
        language=user.language.value,
        oauth_providers=[
            OAuthProviderInfoResponse(provider=p.provider, provider_email=p.provider_email)
            for p in providers
        ],
    )


async def _issue_and_set(
    user: UserDto,
    response: Response,
    config: AppConfig,
    auth_session: AuthSessionDao,
) -> AuthResponse:
    access_token, refresh_token, auth_response = await issue_session(user, config, auth_session)
    set_auth_cookies(response, access_token, refresh_token)
    return auth_response


# ── Redirect / handshake sign-in helpers ─────────────────────────────────────────


async def _enforce_auth_rate_limit(
    request: Request,
    config: AppConfig,
    rate_limiter: RateLimiter,
    scope: str,
    limit: int,
) -> None:
    # Budgets are shared with the OAuth block: these are all the same kind of
    # anonymous, account-creating handshake, and two numbers do not justify a second
    # config section that would inevitably drift from the first.
    window = config.oauth.rate_window_seconds
    ip = get_client_ip(request, config)
    too_many = HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests"
    )
    if not await rate_limiter.hit(scope, ip, limit=limit, window_seconds=window):
        raise too_many
    # Checked second, for the same reason as the OTP global cap: a single abusive IP is
    # rejected above without spending the shared budget, and per-IP attribution is only
    # ever as good as the proxy chain — while this path can create accounts.
    if not await rate_limiter.hit("oauth_global", "all", limit=limit * 100, window_seconds=window):
        raise too_many


def _redirect_to_provider(started: OAuthFlowStarted) -> RedirectResponse:
    response = RedirectResponse(url=started.authorize_url, status_code=status.HTTP_302_FOUND)
    # SameSite=Lax is both required and sufficient here: the callback arrives as a
    # cross-site *top-level GET navigation*, which Lax permits. It is also why the flow
    # must stay on response_mode=query — a cross-site POST would not carry this cookie.
    response.set_cookie(
        _BINDING_COOKIE,
        started.binding,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=started.ttl_seconds,
        path=_BINDING_COOKIE_PATH,
    )
    return response


def _binding_matches(request: Request, expected_hash: str) -> bool:
    binding = request.cookies.get(_BINDING_COOKIE)
    if not binding:
        return False
    return hmac.compare_digest(hash_binding(binding), expected_hash)


def _oauth_redirect(
    config: AppConfig,
    *,
    mode: OAuthFlowMode,
    provider: OAuthProvider,
    code: Optional[str] = None,
    merged: bool = False,
) -> RedirectResponse:
    """Bounce back to the SPA. The base is server config and every query value comes
    from a closed set, so nothing user-controlled is reflected and there is no
    open-redirect surface to allowlist."""
    params = {
        "status": "error" if code else "ok",
        "mode": mode,
        "provider": provider.value,
    }
    if code:
        params["code"] = code
    elif merged:
        params["merged"] = "1"

    response = RedirectResponse(
        url=f"{config.oauth_public_base_url}/auth/callback?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )
    # The URL this handler was reached on carries `code`/`state`. Nothing here renders
    # HTML that could leak them, but the header is free insurance.
    response.headers["Referrer-Policy"] = "no-referrer"
    response.delete_cookie(
        _BINDING_COOKIE, path=_BINDING_COOKIE_PATH, httponly=True, secure=True, samesite="lax"
    )
    return response


async def _complete_login(
    config: AppConfig,
    provider: OAuthProvider,
    flow: OAuthFlowState,
    code: str,
    *,
    authenticate_oauth: AuthenticateOAuth,
    auth_session: AuthSessionDao,
) -> RedirectResponse:
    user = await authenticate_oauth.system(
        AuthenticateOAuthDto(
            provider=provider,
            code=code,
            code_verifier=flow.code_verifier,
            referral_code=flow.referral_code,
        )
    )
    response = _oauth_redirect(config, mode="login", provider=provider)
    # Same session issuance as every other sign-in — there is no second auth system.
    await _issue_and_set(user, response, config, auth_session)
    return response


async def _complete_link(
    config: AppConfig,
    provider: OAuthProvider,
    flow: OAuthFlowState,
    code: str,
    *,
    link_oauth: LinkOAuthProvider,
    user_dao: UserDao,
) -> RedirectResponse:
    # The actor comes from the bound state, not the access-token cookie: a 15-minute
    # token can easily expire while the user sits on the provider's consent screen.
    actor = await user_dao.get_by_id(flow.actor_user_id) if flow.actor_user_id is not None else None
    if actor is None:
        return _oauth_redirect(config, mode="link", provider=provider, code="state_invalid")
    if actor.is_blocked:
        return _oauth_redirect(config, mode="link", provider=provider, code="blocked")

    result = await link_oauth(
        actor,
        LinkOAuthProviderDto(provider=provider, code=code, code_verifier=flow.code_verifier),
    )
    return _oauth_redirect(config, mode="link", provider=provider, merged=result.merged)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@inject
async def register_public_user(
    body: RegisterRequest,
    response: Response,
    config: FromDishka[AppConfig],
    register_email_user: FromDishka[RegisterEmailUser],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await register_email_user.system(
        RegisterEmailUserDto(
            email=body.email,
            password=body.password,
            name=body.name,
            referral_code=body.referral_code,
        )
    )
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/login", response_model=AuthResponse)
@inject
async def login_public_user(
    body: LoginRequest,
    response: Response,
    config: FromDishka[AppConfig],
    login_email_user: FromDishka[LoginEmailUser],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await login_email_user.system(
        LoginEmailUserDto(email=body.email, password=body.password)
    )
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/email/request-code", response_model=RequestEmailLoginCodeResponse)
@inject
async def request_email_login_code(
    body: RequestEmailLoginCodeRequest,
    request: Request,
    request_login_code: FromDishka[RequestEmailLoginCode],
    config: FromDishka[AppConfig],
) -> RequestEmailLoginCodeResponse:
    try:
        result = await request_login_code.system(
            RequestEmailLoginCodeDto(
                email=body.email,
                referral_code=body.referral_code,
                ip=get_client_ip(request, config),
                turnstile_token=body.turnstile_token,
            )
        )
    except EmailDeliveryDisabledError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    except EmailDeliveryError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return RequestEmailLoginCodeResponse(
        success=True, target_email=result.target_email, expires_at=result.expires_at
    )


@router.post("/email/verify-code", response_model=AuthResponse)
@inject
async def verify_email_login_code(
    body: VerifyEmailLoginCodeRequest,
    response: Response,
    config: FromDishka[AppConfig],
    verify_login_code: FromDishka[VerifyEmailLoginCode],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await verify_login_code.system(VerifyEmailLoginCodeDto(email=body.email, code=body.code))
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/email/verify-link", response_model=AuthResponse)
@inject
async def verify_email_login_link(
    body: VerifyEmailLoginLinkRequest,
    response: Response,
    config: FromDishka[AppConfig],
    verify_login_link: FromDishka[VerifyEmailLoginLink],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    """Consume a mailed one-tap sign-in link.

    A POST, not a GET on the link itself: mail scanners and link-preview crawlers follow
    URLs in email, and a link that signed the user in on open would be spent before they
    ever clicked it.
    """
    user = await verify_login_link.system(VerifyEmailLoginLinkDto(token=body.token))
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/refresh", response_model=AuthResponse)
@inject
async def refresh_access_token(
    request: Request,
    response: Response,
    config: FromDishka[AppConfig],
    refresh_session: FromDishka[RefreshSession],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    user = await refresh_session.system(RefreshSessionDto(refresh_token=refresh_token))
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/logout", response_model=LogoutResponse)
@inject
async def logout(
    request: Request,
    response: Response,
    user: CurrentUser,
    auth_session: FromDishka[AuthSessionDao],
) -> LogoutResponse:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await auth_session.revoke_refresh_token(refresh_token)
    clear_auth_cookies(response)
    return LogoutResponse(success=True)


@router.post("/telegram", response_model=AuthResponse)
@inject
async def telegram_login(
    body: TelegramAuthRequest,
    response: Response,
    config: FromDishka[AppConfig],
    authenticate_telegram: FromDishka[AuthenticateTelegram],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await authenticate_telegram.system(
        TelegramAuthData(
            id=body.id,
            first_name=body.first_name,
            last_name=body.last_name,
            username=body.username,
            payload=body.model_dump(exclude_none=True),
        )
    )
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/telegram/webapp", response_model=AuthResponse)
@inject
async def telegram_webapp_login(
    body: TelegramWebAppAuthRequest,
    response: Response,
    config: FromDishka[AppConfig],
    authenticate_webapp: FromDishka[AuthenticateTelegramWebApp],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await authenticate_webapp.system(body.init_data)
    return await _issue_and_set(user, response, config, auth_session)


@router.post("/telegram/link", response_model=TelegramLinkResponse)
@inject
async def link_telegram_account(
    body: TelegramAuthRequest,
    user: CurrentUser,
    link_telegram: FromDishka[LinkTelegram],
    oauth_dao: FromDishka[UserOAuthProviderDao],
) -> TelegramLinkResponse:
    result = await link_telegram(
        user,
        LinkTelegramData(
            id=body.id,
            username=body.username,
            payload=body.model_dump(exclude_none=True),
        ),
    )
    # Read the providers AFTER the call: a merge can absorb an account that carried
    # its own social identities, and they are repointed onto the survivor.
    providers = await oauth_dao.get_user_providers(result.user.id)
    return TelegramLinkResponse(
        **_to_me_response(result.user, providers).model_dump(), merged=result.merged
    )


@router.post("/telegram/bot-login/start", response_model=BotLoginStartResponse)
@inject
async def bot_login_start(
    request: Request,
    response: Response,
    config: FromDishka[AppConfig],
    start_bot_login: FromDishka[StartBotLogin],
    rate_limiter: FromDishka[RateLimiter],
) -> BotLoginStartResponse:
    """Begin a sign-in the user confirms inside the bot.

    First-party alternative to the Telegram Login Widget, which depends on a script
    and an iframe from telegram.org — the login page already has a branch for it
    failing to load.
    """
    await _enforce_auth_rate_limit(
        request, config, rate_limiter, "bot_login_ip", config.oauth.start_max_per_ip
    )
    started = await start_bot_login.system(StartBotLoginDto(ip=get_client_ip(request, config)))
    # Binds the confirmation to THIS browser: without this cookie an approved token is
    # useless, which is what defeats showing someone a QR from an attacker's screen.
    response.set_cookie(
        _BOT_LOGIN_COOKIE,
        started.binding,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=started.expires_in,
        path=_BOT_LOGIN_COOKIE_PATH,
    )
    return BotLoginStartResponse(
        token=started.token,
        url=started.url,
        qr_png_base64=started.qr_png_base64,
        expires_in=started.expires_in,
    )


@router.get("/telegram/bot-login/status", response_model=BotLoginStatusResponse)
@inject
async def bot_login_status(
    bot_login_dao: FromDishka[BotLoginDao],
    token: str = Query(min_length=16, max_length=128),
) -> BotLoginStatusResponse:
    """Poll for the decision. Deliberately polling, not SSE: an anonymous long-lived
    stream is a much larger abuse surface than a request every couple of seconds for
    at most two minutes, and each SSE route needs its own nginx location."""
    pending = await bot_login_dao.get(token)
    # A vanished request is indistinguishable from one that never existed, which is
    # the right answer either way — the client offers a retry.
    return BotLoginStatusResponse(status=pending.status if pending else "expired")


@router.post("/telegram/bot-login/claim", response_model=AuthResponse)
@inject
async def bot_login_claim(
    body: BotLoginClaimRequest,
    request: Request,
    response: Response,
    config: FromDishka[AppConfig],
    claim_bot_login: FromDishka[ClaimBotLogin],
    auth_session: FromDishka[AuthSessionDao],
) -> AuthResponse:
    user = await claim_bot_login.system(
        ClaimBotLoginDto(token=body.token, binding=request.cookies.get(_BOT_LOGIN_COOKIE))
    )
    response.delete_cookie(
        _BOT_LOGIN_COOKIE, path=_BOT_LOGIN_COOKIE_PATH, httponly=True, secure=True, samesite="lax"
    )
    return await _issue_and_set(user, response, config, auth_session)


@router.get("/oauth/{provider}/start")
@inject
async def oauth_start(
    provider: OAuthProvider,
    request: Request,
    config: FromDishka[AppConfig],
    start_oauth: FromDishka[StartOAuth],
    rate_limiter: FromDishka[RateLimiter],
    ref: Optional[str] = Query(default=None, min_length=3, max_length=64, pattern=r"^[\w-]+$"),
) -> RedirectResponse:
    """Open a social sign-in — a browser redirect, not an API call."""
    await _enforce_auth_rate_limit(
        request, config, rate_limiter, "oauth_start_ip", config.oauth.start_max_per_ip
    )
    started = await start_oauth.system(
        StartOAuthDto(provider=provider, mode="login", referral_code=ref)
    )
    return _redirect_to_provider(started)


@router.get("/oauth/{provider}/link/start")
@inject
async def oauth_link_start(
    provider: OAuthProvider,
    request: Request,
    user: CurrentUser,
    config: FromDishka[AppConfig],
    start_oauth: FromDishka[StartOAuth],
    rate_limiter: FromDishka[RateLimiter],
) -> RedirectResponse:
    """Attach a provider to the signed-in account.

    A separate route rather than a `mode` parameter, so that link mode is gated by an
    actual authentication dependency and cannot simply be asked for.
    """
    await _enforce_auth_rate_limit(
        request, config, rate_limiter, "oauth_start_ip", config.oauth.start_max_per_ip
    )
    started = await start_oauth.system(
        StartOAuthDto(provider=provider, mode="link", actor_user_id=user.id)
    )
    return _redirect_to_provider(started)


@router.get("/oauth/{provider}/callback")
@inject
async def oauth_callback(
    provider: OAuthProvider,
    request: Request,
    config: FromDishka[AppConfig],
    state_dao: FromDishka[OAuthStateDao],
    user_dao: FromDishka[UserDao],
    authenticate_oauth: FromDishka[AuthenticateOAuth],
    link_oauth: FromDishka[LinkOAuthProvider],
    auth_session: FromDishka[AuthSessionDao],
    rate_limiter: FromDishka[RateLimiter],
    code: Optional[str] = Query(default=None, max_length=2048),
    state: Optional[str] = Query(default=None, max_length=512),
    error: Optional[str] = Query(default=None, max_length=256),
    error_description: Optional[str] = Query(default=None, max_length=1024),
) -> RedirectResponse:
    """Land the provider's redirect: verify, resolve, issue the session, bounce home.

    Answers with a 302 in every case, including failure — the user is mid-navigation
    from the provider and must end up back on the site, never staring at a JSON error
    on an API URL.
    """
    mode: OAuthFlowMode = "login"
    try:
        await _enforce_auth_rate_limit(
            request, config, rate_limiter, "oauth_callback_ip", config.oauth.callback_max_per_ip
        )

        flow = await state_dao.consume(state) if state else None
        # A missing/expired state, a provider mismatch, or a binding that does not match
        # the cookie this browser was given are all the same answer: this callback did
        # not come from a flow we started here.
        if (
            flow is None
            or flow.provider != provider
            or not _binding_matches(request, flow.binding_hash)
        ):
            return _oauth_redirect(config, mode=mode, provider=provider, code="state_invalid")

        mode = flow.mode

        if error:
            logger.info(
                f"OAuth provider '{provider}' returned error: {error} ({error_description})"
            )
            return _oauth_redirect(
                config,
                mode=mode,
                provider=provider,
                code=_PROVIDER_ERROR_TO_CODE.get(error, "provider_error"),
            )
        if not code:
            return _oauth_redirect(config, mode=mode, provider=provider, code="state_invalid")

        if mode == "link":
            return await _complete_link(
                config, provider, flow, code, link_oauth=link_oauth, user_dao=user_dao
            )
        return await _complete_login(
            config,
            provider,
            flow,
            code,
            authenticate_oauth=authenticate_oauth,
            auth_session=auth_session,
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else ""
        mapped = _DETAIL_TO_CODE.get(detail) or _STATUS_TO_CODE.get(e.status_code) or "internal"
        logger.info(f"OAuth '{provider}' {mode} failed: {e.status_code} {detail} -> {mapped}")
        return _oauth_redirect(config, mode=mode, provider=provider, code=mapped)
    except OAuthExchangeError as e:
        logger.warning(f"OAuth '{provider}' exchange failed: {e}")
        return _oauth_redirect(config, mode=mode, provider=provider, code="provider_error")
    except Exception as e:  # noqa: BLE001 - the user must never be stranded on an API URL
        logger.exception(f"OAuth '{provider}' callback crashed: {e}")
        return _oauth_redirect(config, mode=mode, provider=provider, code="internal")


@router.delete("/oauth/{provider}", response_model=MeResponse)
@inject
async def unlink_oauth_provider(
    provider: OAuthProvider,
    user: CurrentUser,
    unlink_oauth: FromDishka[UnlinkOAuthProvider],
    oauth_dao: FromDishka[UserOAuthProviderDao],
) -> MeResponse:
    updated = await unlink_oauth(user, UnlinkOAuthProviderDto(provider=provider))
    return _to_me_response(updated, await oauth_dao.get_user_providers(updated.id))


@router.get("/me", response_model=MeResponse)
@inject
async def get_public_user_profile(
    user: CurrentUser,
    oauth_dao: FromDishka[UserOAuthProviderDao],
) -> MeResponse:
    return _to_me_response(user, await oauth_dao.get_user_providers(user.id))


@router.post("/change-password", response_model=ChangePasswordResponse)
@inject
async def change_public_user_password(
    body: ChangePasswordRequest,
    response: Response,
    user: CurrentUser,
    config: FromDishka[AppConfig],
    change_password: FromDishka[ChangePassword],
    auth_session: FromDishka[AuthSessionDao],
) -> ChangePasswordResponse:
    updated = await change_password(
        user,
        ChangePasswordDto(current_password=body.current_password, new_password=body.new_password),
    )
    # All sessions were revoked; rotate the current device into a fresh session.
    await _issue_and_set(updated, response, config, auth_session)
    return ChangePasswordResponse(success=True)


@router.post("/email/change", response_model=ChangeEmailResponse)
@inject
async def change_email(
    body: ChangeEmailRequest,
    user: CurrentUser,
    change_email_uc: FromDishka[ChangeEmail],
) -> ChangeEmailResponse:
    await change_email_uc(user, ChangeEmailDto(email=body.email))
    return ChangeEmailResponse(success=True, pending_email=body.email)


@router.post("/email/request-verification", response_model=RequestEmailVerificationCodeResponse)
@inject
async def request_email_verification_code(
    body: RequestEmailVerificationCodeRequest,
    user: CurrentUser,
    request_verification: FromDishka[RequestEmailVerification],
) -> RequestEmailVerificationCodeResponse:
    try:
        result = await request_verification(user, RequestEmailVerificationDto(email=body.email))
    except EmailDeliveryDisabledError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    except EmailDeliveryError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return RequestEmailVerificationCodeResponse(
        success=True, target_email=result.target_email, expires_at=result.expires_at
    )


@router.post("/email/confirm", response_model=ConfirmEmailVerificationResponse)
@inject
async def confirm_email_verification(
    body: ConfirmEmailVerificationRequest,
    user: CurrentUser,
    confirm_verification: FromDishka[ConfirmEmailVerification],
) -> ConfirmEmailVerificationResponse:
    result = await confirm_verification(user, ConfirmEmailVerificationDto(code=body.code))
    return ConfirmEmailVerificationResponse(success=True, email=result.email, merged=result.merged)
