from dataclasses import dataclass, fields
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import SecretStr

from src.core.enums import Currency, PaymentGatewayType, PlategaPaymentMethod

from .base import BaseDto, TrackableMixin


@dataclass(kw_only=True)
class PaymentResultDto:
    id: UUID
    url: Optional[str] = None


@dataclass(kw_only=True)
class PaymentGatewayDto(BaseDto, TrackableMixin):
    order_index: int = 0
    type: PaymentGatewayType
    currency: Currency

    is_active: bool = False
    settings: Optional["AnyGatewaySettingsDto"] = None

    @property
    def requires_webhook(self) -> bool:
        return self.type not in {
            PaymentGatewayType.TELEGRAM_STARS,
            PaymentGatewayType.CRYPTOMUS,
            PaymentGatewayType.HELEKET,
            PaymentGatewayType.FREEKASSA,
            PaymentGatewayType.PAYMASTER,
        }


@dataclass(kw_only=True)
class GatewaySettingsDto(TrackableMixin):
    display_name: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        for f in fields(self):
            if f.name in {"created_at", "updated_at", "type", "display_name"}:
                continue
            if getattr(self, f.name) is None:
                return False
        return True

    @property
    def as_list(self) -> list[dict[str, Any]]:
        return [
            {"field": f.name, "value": getattr(self, f.name)}
            for f in fields(self)
            if f.name not in {"type", "created_at", "updated_at"} and not f.name.startswith("_")
        ]


@dataclass(kw_only=True)
class TelegramStarsGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.TELEGRAM_STARS] = PaymentGatewayType.TELEGRAM_STARS


@dataclass(kw_only=True)
class YooKassaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.YOOKASSA] = PaymentGatewayType.YOOKASSA
    shop_id: Optional[str] = None
    api_key: Optional[SecretStr] = None
    customer: Optional[str] = None
    vat_code: Optional[int] = None


@dataclass(kw_only=True)
class YooMoneyGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.YOOMONEY] = PaymentGatewayType.YOOMONEY
    wallet_id: Optional[str] = None
    secret_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class CryptomusGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.CRYPTOMUS] = PaymentGatewayType.CRYPTOMUS
    merchant_id: Optional[str] = None
    api_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class HeleketGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.HELEKET] = PaymentGatewayType.HELEKET
    merchant_id: Optional[str] = None
    api_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class CryptoPayGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.CRYPTOPAY] = PaymentGatewayType.CRYPTOPAY
    api_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class FreeKassaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.FREEKASSA] = PaymentGatewayType.FREEKASSA
    shop_id: Optional[int] = None
    api_key: Optional[SecretStr] = None
    secret_word_2: Optional[SecretStr] = None
    payment_system_id: Optional[int] = None
    customer_email: Optional[str] = None
    customer_ip: Optional[str] = None


@dataclass(kw_only=True)
class MulenPayGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.MULENPAY] = PaymentGatewayType.MULENPAY
    api_key: Optional[SecretStr] = None
    secret_key: Optional[SecretStr] = None
    shop_id: Optional[int] = None
    vat_code: Optional[int] = None


@dataclass(kw_only=True)
class PayMasterGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.PAYMASTER] = PaymentGatewayType.PAYMASTER
    merchant_id: Optional[str] = None
    api_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class PlategaMethodConfigDto:
    """A single Platega payment method exposed to the user (id = PlategaPaymentMethod).

    ``label`` is an optional admin-set display name; when None the bot falls back to the
    method's default i18n label.
    """

    id: int
    enabled: bool = False
    label: Optional[str] = None


@dataclass(kw_only=True)
class PlategaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.PLATEGA] = PaymentGatewayType.PLATEGA
    merchant_id: Optional[str] = None
    api_key: Optional[SecretStr] = None
    # Hard-pin a single method (advanced): forces that one method for everyone, no picker.
    payment_method: Optional[int] = None
    # User-selectable methods (СБП / карта / крипта …) configured in the dashboard. When
    # 2+ are enabled the bot shows an in-bot picker; managed via a dedicated screen, so it
    # is excluded from the generic field editor. None -> Platega's own multi-method page.
    methods: Optional[list[PlategaMethodConfigDto]] = None

    @property
    def is_configured(self) -> bool:
        return self.merchant_id is not None and self.api_key is not None

    def enabled_methods(self) -> list[PlategaMethodConfigDto]:
        return [m for m in (self.methods or []) if m.enabled]

    @staticmethod
    def default_methods() -> list[PlategaMethodConfigDto]:
        """Full method list with sensible defaults — used to seed the config on first edit."""
        enabled = {m.value for m in PlategaPaymentMethod.default_enabled()}
        return [
            PlategaMethodConfigDto(id=method.value, enabled=method.value in enabled)
            for method in PlategaPaymentMethod
        ]


@dataclass(kw_only=True)
class RoboKassaGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.ROBOKASSA] = PaymentGatewayType.ROBOKASSA
    merchant_login: Optional[str] = None
    password1: Optional[SecretStr] = None
    password2: Optional[SecretStr] = None


@dataclass(kw_only=True)
class UrlPayGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.URLPAY] = PaymentGatewayType.URLPAY
    shop_id: Optional[int] = None
    api_key: Optional[SecretStr] = None
    secret_key: Optional[SecretStr] = None
    vat_code: Optional[int] = None


@dataclass(kw_only=True)
class WataGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.WATA] = PaymentGatewayType.WATA
    api_key: Optional[SecretStr] = None


@dataclass(kw_only=True)
class ValutixGatewaySettingsDto(GatewaySettingsDto):
    type: Literal[PaymentGatewayType.VALUTIX] = PaymentGatewayType.VALUTIX
    api_key: Optional[SecretStr] = None


AnyGatewaySettingsDto = Union[
    TelegramStarsGatewaySettingsDto,
    YooKassaGatewaySettingsDto,
    YooMoneyGatewaySettingsDto,
    CryptomusGatewaySettingsDto,
    HeleketGatewaySettingsDto,
    CryptoPayGatewaySettingsDto,
    FreeKassaGatewaySettingsDto,
    MulenPayGatewaySettingsDto,
    PayMasterGatewaySettingsDto,
    PlategaGatewaySettingsDto,
    RoboKassaGatewaySettingsDto,
    UrlPayGatewaySettingsDto,
    WataGatewaySettingsDto,
    ValutixGatewaySettingsDto,
]
