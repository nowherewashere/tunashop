from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.constants import EMAIL_VERIFICATION_CODE_LENGTH
from src.core.enums import AuthType, OAuthProvider


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=256)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    referral_code: Optional[str] = Field(default=None, min_length=3, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("referral_code")
    @classmethod
    def normalize_referral_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class MigrateTelegramRequest(RegisterRequest):
    pass


class AuthResponse(BaseModel):
    expires_at: datetime
    refresh_expires_at: datetime


class OAuthProviderInfoResponse(BaseModel):
    provider: OAuthProvider
    # Address the provider reported at link time, so the cabinet can say WHICH account
    # is attached. Display only — never matched on (see migration 0053).
    provider_email: Optional[str] = None


class MeResponse(BaseModel):
    telegram_id: Optional[int]
    auth_type: AuthType
    email: Optional[str]
    is_email_verified: bool
    pending_email: Optional[str]
    name: str
    username: Optional[str]
    language: str
    # Linked social identities. Costs one indexed lookup on a tiny table per /auth/me —
    # a deliberate, known price for the cabinet's "Способы входа" section, which needs
    # the list on every load anyway.
    oauth_providers: list[OAuthProviderInfoResponse] = Field(default_factory=list)


class TelegramLinkResponse(MeResponse):
    # True when linking absorbed a separate bot account into this one — the client
    # uses it to reassure the user that dropped devices re-appear on their own.
    merged: bool = False


class ChangePasswordResponse(BaseModel):
    success: bool


class ChangeEmailRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class ChangeEmailResponse(BaseModel):
    success: bool
    pending_email: str


class RequestEmailVerificationCodeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: Optional[str] = Field(
        default=None,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.lower()


class RequestEmailVerificationCodeResponse(BaseModel):
    success: bool
    target_email: str
    expires_at: datetime


class RequestEmailLoginCodeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    referral_code: Optional[str] = Field(default=None, min_length=3, max_length=64)
    turnstile_token: Optional[str] = Field(default=None, max_length=4096)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("referral_code")
    @classmethod
    def normalize_referral_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RequestEmailLoginCodeResponse(BaseModel):
    success: bool
    target_email: str
    expires_at: datetime


class VerifyEmailLoginCodeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    code: str = Field(
        min_length=EMAIL_VERIFICATION_CODE_LENGTH,
        max_length=EMAIL_VERIFICATION_CODE_LENGTH,
        pattern=r"^\d{6}$",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class VerifyEmailLoginLinkRequest(BaseModel):
    # `secrets.token_urlsafe(32)` renders to 43 chars; the bounds leave room to change
    # that without a schema change while still rejecting obvious junk.
    token: str = Field(min_length=32, max_length=128)


class ConfirmEmailVerificationRequest(BaseModel):
    code: str = Field(
        min_length=EMAIL_VERIFICATION_CODE_LENGTH,
        max_length=EMAIL_VERIFICATION_CODE_LENGTH,
        pattern=r"^\d{6}$",
    )


class ConfirmEmailVerificationResponse(BaseModel):
    success: bool
    email: str
    # True when confirming this email absorbed a separate site account into the current
    # one — the mirror of `TelegramLinkResponse.merged`. The client re-reads /auth/me
    # afterwards, since a merge can also pull in the absorbed account's Telegram.
    merged: bool = False


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


class TelegramWebAppAuthRequest(BaseModel):
    init_data: str


class BotLoginStartResponse(BaseModel):
    # Handed back so the caller can poll and claim. Not a secret from this browser —
    # it is embedded in `url` and the QR below, and on its own it is useless without
    # the httpOnly binding cookie set alongside it.
    token: str
    # t.me deep link that opens the bot with a one-time confirmation token.
    url: str
    # QR of the same URL, rendered server-side so the SPA needs no QR library and a
    # desktop visitor without Telegram Desktop can confirm from their phone.
    qr_png_base64: str
    expires_in: int


class BotLoginStatusResponse(BaseModel):
    # pending | approved | declined | expired — `expired` is synthesised when the
    # request is simply gone, so the client can tell "still waiting" from "too late".
    status: str


class BotLoginClaimRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class LogoutResponse(BaseModel):
    success: bool
