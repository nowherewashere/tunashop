from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from src.core.enums import PaymentGatewayType, PromocodeRewardType


@dataclass(frozen=True)
class UserPaymentStatsDto:
    currency: str
    total_amount: float


@dataclass(frozen=True)
class UserStatisticsDto:
    last_payment_at: Optional[datetime]
    payment_amounts: list[UserPaymentStatsDto]
    registered_at: datetime
    referrer_telegram_id: Optional[int]
    referrer_email: Optional[str]
    referrer_username: Optional[str]
    referrals_invited: int
    referrals_paying: int
    referral_earned_kop: int
    referral_spent_kop: int
    referral_withdrawn_kop: int

    @property
    def referral_balance_kop(self) -> int:
        return self.referral_earned_kop - self.referral_spent_kop - self.referral_withdrawn_kop


@dataclass(frozen=True)
class ReferralStatisticsDto:
    """Shop-wide referral picture: attribution counts plus the money ledger.

    Amounts are kopecks — formatting to ₽ belongs to the presentation layer.
    """

    total_referrals: int
    unique_referrers: int
    top_referrer_referrals_count: int
    paying_referrals: int = 0
    total_earned_kop: int = 0
    total_spent_kop: int = 0
    total_withdrawn_kop: int = 0
    open_payouts_count: int = 0
    open_payouts_kop: int = 0
    top_referrer_id: Optional[int] = None
    top_referrer_telegram_id: Optional[int] = None
    top_referrer_username: Optional[str] = None
    top_referrer_email: Optional[str] = None

    @property
    def total_balance_kop(self) -> int:
        """Money sitting on user balances: EARNED − SPENT − WITHDRAWN."""
        return self.total_earned_kop - self.total_spent_kop - self.total_withdrawn_kop


@dataclass(frozen=True)
class SubscriptionStatsDto:
    total: int
    total_active: int
    total_disabled: int
    total_limited: int
    total_expired: int
    active_trial: int
    expiring_soon: int
    total_unlimited: int
    total_traffic: int
    total_devices: int


@dataclass(frozen=True)
class PlanSubStatsDto:
    plan_id: int
    plan_name: str
    total: int
    total_active: int
    total_disabled: int
    total_limited: int
    total_expired: int
    expiring_soon: int
    total_unlimited: int
    total_traffic: int
    total_devices: int
    popular_duration: int


@dataclass(frozen=True)
class PlanIncomeDto:
    plan_id: int
    currency: str
    total_income: float


@dataclass(frozen=True)
class PromocodeStatisticsDto:
    total_promocodes: int
    active_promocodes: int
    total_activations: int
    activations_today: int
    activations_week: int
    activations_month: int
    issued_days: int
    issued_traffic: int
    issued_devices: int
    issued_subscriptions: int
    issued_personal_discounts: int
    issued_purchase_discounts: int


@dataclass(frozen=True)
class PromocodeDetailStatisticsDto:
    code: str
    reward_type: PromocodeRewardType
    reward: Optional[int]
    plan_snapshot: Optional[dict[str, Any]]
    is_active: bool
    is_reusable: bool
    created_at: datetime
    expires_at: Optional[datetime]
    max_activations: Optional[int]
    total_activations: int
    activations_today: int
    activations_week: int
    activations_month: int


@dataclass(frozen=True)
class GatewayStatsDto:
    gateway_type: PaymentGatewayType
    total_income: Decimal
    daily_income: Decimal
    weekly_income: Decimal
    monthly_income: Decimal
    last_month_income: Decimal
    paid_count: int
    total_discounts: Decimal
    total_transactions: int
    completed_transactions: int
    free_transactions: int
