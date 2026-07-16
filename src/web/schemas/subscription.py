from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.enums import PaymentGatewayType


class SubscriptionInfoResponse(BaseModel):
    user_remna_id: str
    status: str
    is_trial: bool
    traffic_limit: int
    device_limit: int
    traffic_limit_strategy: str
    expire_at: datetime
    url: str
    plan_name: str
    # Per-plan flag/location string of the live plan (opaque emoji text), or null when
    # the plan has none set or was removed. Resolved live, not from the snapshot.
    plan_locations: Optional[str] = None
    plan_duration_days: int
    used_traffic_bytes: Optional[int] = None
    lifetime_used_traffic_bytes: Optional[int] = None
    online_at: Optional[datetime] = None


class DeviceResponse(BaseModel):
    hwid: str
    platform: Optional[str] = None
    device_model: Optional[str] = None
    os_version: Optional[str] = None
    user_agent: Optional[str] = None


class DevicesResponse(BaseModel):
    devices: list[DeviceResponse]
    current_count: int
    max_count: int


class DeviceDeleteResponse(BaseModel):
    deleted: bool


class DevicesDeleteAllResponse(BaseModel):
    success: bool


class PromocodeActivateRequest(BaseModel):
    code: str


class PromocodeActivateResponse(BaseModel):
    success: bool
    reward_type: str


class TrialPurchaseRequest(BaseModel):
    gateway_type: PaymentGatewayType
    payment_method: Optional[int] = None


class ReissueResponse(BaseModel):
    success: bool


class PurchaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    plan_code: str = Field(min_length=3, max_length=64)
    duration_days: int = Field(ge=0)
    gateway_type: PaymentGatewayType
    # Optional gateway-specific method code (Platega: СБП / карта / крипта). Ignored by
    # gateways that don't support method selection.
    payment_method: Optional[int] = None


class ExtendRequest(BaseModel):
    duration_days: int = Field(ge=0)
    gateway_type: PaymentGatewayType
    payment_method: Optional[int] = None


class PaymentInitResponse(BaseModel):
    payment_id: str
    payment_url: Optional[str] = None
    purchase_type: str
    status: str
    is_free: bool
    final_amount: str
    currency: str


class PlategaMethodOfferResponse(BaseModel):
    id: int
    label: str


class GatewayOfferResponse(BaseModel):
    gateway_type: PaymentGatewayType
    currency: str
    currency_symbol: str
    # User-selectable Platega methods (СБП / карта / крипта …). None for other gateways,
    # or when Platega is hard-pinned / has no methods configured (falls back to a single
    # pay button using Platega's own page).
    methods: Optional[list[PlategaMethodOfferResponse]] = None


class DurationGatewayPriceResponse(BaseModel):
    gateway_type: PaymentGatewayType
    currency: str
    currency_symbol: str
    original_amount: str
    discount_percent: int
    final_amount: str
    is_free: bool


class DurationOfferResponse(BaseModel):
    days: int
    prices: list[DurationGatewayPriceResponse]


class TrialActivateResponse(BaseModel):
    is_free: bool
    activated: bool
    duration_days: int
    gateways: list[DurationGatewayPriceResponse] = []


class PlanOfferResponse(BaseModel):
    id: int
    public_code: str
    name: str
    description: Optional[str] = None
    # Per-plan flag/location string (opaque emoji text), e.g. "🇩🇪 | 🇯🇵 | 🇷🇺".
    locations: Optional[str] = None
    traffic_limit: int
    device_limit: int
    type: str
    recommended_purchase_type: str
    durations: list[DurationOfferResponse]


class SubscriptionOffersResponse(BaseModel):
    gateways: list[GatewayOfferResponse]
    plans: list[PlanOfferResponse]
    has_current_subscription: bool
    current_subscription_status: Optional[str] = None
