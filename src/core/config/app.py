import re
from pathlib import Path
from typing import Optional, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_core.core_schema import FieldValidationInfo

from src.core.constants import API_V1, ASSETS_DEFAULT_DIR, ASSETS_DIR, PAYMENTS_WEBHOOK_PATH
from src.core.enums import Locale, PaymentGatewayType
from src.core.types import LocaleList, StringList
from src.core.utils.validators import is_valid_domain

from .base import BaseConfig
from .bot import BotConfig
from .build import BuildConfig
from .database import DatabaseConfig
from .email import EmailConfig
from .log import LogConfig
from .onboarding import OnboardingConfig
from .payout import PayoutConfig
from .redis import RedisConfig
from .referral import ReferralConfig
from .remnawave import RemnawaveConfig
from .stars import StarsConfig
from .support import SupportConfig
from .validators import validate_not_change_me


class AppConfig(BaseConfig, env_prefix="APP_"):
    domain: SecretStr
    host: str = "0.0.0.0"
    port: int = 5000

    locales: LocaleList = LocaleList([Locale.RU])  # TODO: Change to EN
    default_locale: Locale = Locale.RU  # TODO: Change to EN

    crypt_key: SecretStr
    jwt_secret: Optional[SecretStr] = None
    api_key: Optional[SecretStr] = None
    # Cloudflare Turnstile (captcha on passwordless code requests). Secret is
    # server-side; site key is public and served to the frontend via /public/config.
    # When the secret is unset, verification is skipped (captcha disabled).
    turnstile_secret: Optional[SecretStr] = Field(default=None, validation_alias="TURNSTILE_SECRET")
    turnstile_site_key: str = Field(default="", validation_alias="TURNSTILE_SITE_KEY")
    assets_dir: Path = ASSETS_DIR
    origins: StringList = StringList("")
    swagger_enabled: bool = False
    web_enabled: bool = Field(default=False, validation_alias="WEB_ENABLED")
    web_cabinet_url: str = Field(default="", validation_alias="WEB_CABINET_URL")
    # Optional marketing/redirect site that maps /r/<code> to the bot referral
    # link (spec §4.7 second link). Empty ⇒ only the bot link is shown.
    referral_site_url: str = Field(default="", validation_alias="REFERRAL_SITE_URL")
    # Editable list of available server locations, shared identically across all
    # plans and rendered on the plan-selection screen. Change without a rebuild.
    plan_locations: str = Field(
        default="🇩🇪 | 🇯🇵 | 🇷🇺 | 🇨🇭", validation_alias="PLAN_LOCATIONS"
    )

    bot: BotConfig = Field(default_factory=BotConfig)
    remnawave: RemnawaveConfig = Field(default_factory=RemnawaveConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    onboarding: OnboardingConfig = Field(default_factory=OnboardingConfig)
    referral: ReferralConfig = Field(default_factory=ReferralConfig)
    payout: PayoutConfig = Field(default_factory=PayoutConfig)
    stars: StarsConfig = Field(default_factory=StarsConfig)
    support: SupportConfig = Field(default_factory=SupportConfig)

    @property
    def default_assets_dir(self) -> Path:
        return ASSETS_DEFAULT_DIR

    @property
    def banners_dir(self) -> Path:
        return self.assets_dir / "banners"

    @property
    def videos_dir(self) -> Path:
        return self.assets_dir / "videos"

    @property
    def translations_dir(self) -> Path:
        return self.assets_dir / "translations"

    @property
    def default_banners_dir(self) -> Path:
        return self.default_assets_dir / "banners"

    @property
    def default_videos_dir(self) -> Path:
        return self.default_assets_dir / "videos"

    @property
    def default_translations_dir(self) -> Path:
        return self.default_assets_dir / "translations"

    def get_webhook(self, gateway_type: PaymentGatewayType) -> str:
        domain = f"https://{self.domain.get_secret_value()}"
        path = f"{API_V1 + PAYMENTS_WEBHOOK_PATH}/{gateway_type.lower()}"
        return domain + path

    @classmethod
    def get(cls) -> Self:
        return cls()

    @model_validator(mode="after")
    def validate_web_secrets(self) -> "AppConfig":
        if self.web_enabled:
            if not self.api_key:
                raise ValueError(
                    "APP_API_KEY must be set when WEB_ENABLED=true; "
                    "do not reuse APP_CRYPT_KEY for API authentication"
                )
            if not self.jwt_secret:
                raise ValueError(
                    "APP_JWT_SECRET must be set when WEB_ENABLED=true; "
                    "do not reuse APP_CRYPT_KEY for JWT signing"
                )
        return self

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not is_valid_domain(field.get_secret_value()):
            raise ValueError("APP_DOMAIN has invalid format")

        return field

    @field_validator("crypt_key")
    @classmethod
    def validate_crypt_key(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)

        if not re.match(r"^[A-Za-z0-9+/=]{44}$", field.get_secret_value()):
            raise ValueError("APP_CRYPT_KEY must be a valid 44-character Base64 string")

        return field
