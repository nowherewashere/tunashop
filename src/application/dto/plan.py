from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Self
from uuid import UUID

from remnapy.enums.users import TrafficLimitStrategy

from src.core.enums import Currency, PlanAvailability, PlanType
from src.core.exceptions import PriceNotFoundError
from src.core.utils.converters import quota_months

from .base import BaseDto, TimestampMixin, TrackableMixin
from .traffic_pool import PlanPoolQuotaDto, PoolQuotaSnapshotDto


@dataclass(kw_only=True)
class PlanSnapshotDto:
    id: int

    name: str
    tag: Optional[str] = None

    type: PlanType
    traffic_limit_strategy: TrafficLimitStrategy = TrafficLimitStrategy.NO_RESET

    traffic_limit: int
    device_limit: int
    duration: int

    internal_squads: list[UUID] = field(default_factory=list)
    external_squad: Optional[UUID] = None

    # Premium-location quotas frozen at purchase time, like every other priced field.
    # Optional with an empty default so snapshots written before the feature (and any
    # cached copy of one) still load.
    traffic_pools: list[PoolQuotaSnapshotDto] = field(default_factory=list)

    is_trial: bool = False

    # Amount actually paid for this snapshot's duration, captured at purchase time so
    # a later plan change can convert the remaining value into bonus days (proration).
    # Optional/None for grants without a monetary basis (trial, admin, promo, legacy).
    price: Optional[Decimal] = None
    price_currency: Optional[Currency] = None

    @classmethod
    def from_plan(
        cls,
        plan: "PlanDto",
        duration: int,
        price: Optional[Decimal] = None,
        price_currency: Optional[Currency] = None,
    ) -> Self:
        return cls(
            id=plan.id,
            name=plan.name,
            tag=plan.tag,
            type=plan.type,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            duration=duration,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            # Pool quotas are priced per month, so the term buys a proportionally larger
            # one, spent as a single window instead of reset monthly — hence NO_RESET
            # even for a one-month term, whose window then runs from the purchase rather
            # than being cut in half by the calendar 1st.
            traffic_pools=[
                PoolQuotaSnapshotDto(
                    pool_id=quota.pool_id,
                    quota_gb=quota.quota_gb * quota_months(duration),
                    base_quota_gb=quota.quota_gb,
                    reset_strategy=TrafficLimitStrategy.NO_RESET,
                )
                for quota in plan.pool_quotas
            ],
            is_trial=plan.is_trial,
            price=price,
            price_currency=price_currency,
        )

    @classmethod
    def test(cls) -> "PlanSnapshotDto":
        return cls(
            id=-1,
            name="test",
            tag=None,
            type=PlanType.UNLIMITED,
            traffic_limit=0,
            device_limit=0,
            duration=0,
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            internal_squads=[],
            external_squad=None,
        )


@dataclass(kw_only=True)
class PlanDto(BaseDto, TrackableMixin, TimestampMixin):
    public_code: Optional[str] = None
    name: str = ""
    description: Optional[str] = None
    tag: Optional[str] = None
    # Per-plan flag/location string shown on the plan card (opaque emoji text). Lives on
    # the live plan only — not snapshotted — so admin edits reflect everywhere at once.
    locations: Optional[str] = None

    type: PlanType = PlanType.BOTH
    availability: PlanAvailability = PlanAvailability.ALL
    traffic_limit_strategy: TrafficLimitStrategy = TrafficLimitStrategy.NO_RESET

    traffic_limit: int = 100
    device_limit: int = 1

    allowed_telegram_ids: list[int] = field(default_factory=list)
    allowed_emails: list[str] = field(default_factory=list)
    internal_squads: list[UUID] = field(default_factory=list)
    external_squad: Optional[UUID] = None
    # Metered premium-location quotas. A quota is only meaningful when the pool's
    # squad is also in `internal_squads` — CommitPlan enforces that.
    pool_quotas: list["PlanPoolQuotaDto"] = field(default_factory=list)

    order_index: int = 0
    is_active: bool = False
    is_trial: bool = False

    durations: list["PlanDurationDto"] = field(default_factory=list)

    @property
    def is_unlimited_traffic(self) -> bool:
        return self.type not in {PlanType.TRAFFIC, PlanType.BOTH}

    @property
    def is_unlimited_devices(self) -> bool:
        return self.type not in {PlanType.DEVICES, PlanType.BOTH}

    def get_duration(self, days: int) -> Optional["PlanDurationDto"]:
        return next((d for d in self.durations if d.days == days), None)


@dataclass(kw_only=True)
class PlanDurationDto(BaseDto, TrackableMixin):
    days: int
    order_index: int = 0
    prices: list["PlanPriceDto"] = field(default_factory=list)

    def get_price(self, currency: Currency) -> Decimal:
        price = next((p.price for p in self.prices if p.currency == currency), None)
        if price is None:
            raise PriceNotFoundError(
                f"No price for currency '{currency}' in duration '{self.days}'"
            )
        return price


@dataclass(kw_only=True)
class PlanPriceDto(BaseDto, TrackableMixin):
    currency: Currency
    price: Decimal
