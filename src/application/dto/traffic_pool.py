from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from remnapy.enums.users import TrafficLimitStrategy

from src.core.utils.converters import gb_to_bytes

from .base import BaseDto, TimestampMixin, TrackableMixin


@dataclass(kw_only=True)
class TrafficPoolDto(BaseDto, TrackableMixin, TimestampMixin):
    """A metered group of premium locations, backed by exactly one internal squad."""

    name: str = ""
    internal_squad_uuid: UUID
    is_active: bool = True
    order_index: int = 0


@dataclass(kw_only=True)
class PlanPoolQuotaDto(BaseDto, TrackableMixin):
    """The quota a plan grants on one pool, and how often it resets."""

    pool_id: int
    quota_gb: int
    reset_strategy: TrafficLimitStrategy = TrafficLimitStrategy.MONTH

    @property
    def quota_bytes(self) -> int:
        return gb_to_bytes(self.quota_gb)


@dataclass(kw_only=True)
class PoolQuotaSnapshotDto:
    """A plan's pool quota frozen into ``plan_snapshot`` at purchase time.

    Carries the *priced* part only — the quota and its period. The pool's name and
    squad stay live on ``traffic_pools`` (single source of truth), so renaming a pool
    or fixing its squad reflects everywhere at once, exactly like ``plan.locations``.
    """

    pool_id: int
    quota_gb: int
    reset_strategy: TrafficLimitStrategy = TrafficLimitStrategy.MONTH

    @property
    def quota_bytes(self) -> int:
        return gb_to_bytes(self.quota_gb)


@dataclass(kw_only=True)
class SubscriptionPoolUsageDto(BaseDto, TrackableMixin, TimestampMixin):
    """One subscription's accounting window on one pool."""

    subscription_id: int
    pool_id: int
    period_start: datetime
    # None = below the warning threshold at the last pass (the pass filters
    # server-side, so no exact figure exists under it).
    used_bytes: Optional[int] = None
    is_exhausted: bool = False
    exhausted_at: Optional[datetime] = None
    warned_at: Optional[datetime] = None
    metered_at: Optional[datetime] = None


@dataclass(frozen=True, kw_only=True)
class PoolUsageViewDto:
    """Everything a surface (cabinet, bot, admin card) needs to render one pool."""

    pool_id: int
    name: str
    quota_bytes: int
    # None when the panel could not be reached — render the bar as unknown rather
    # than as zero usage.
    used_bytes: Optional[int] = None
    is_exhausted: bool = False
    reset_at: Optional[datetime] = None

    @property
    def remaining_bytes(self) -> Optional[int]:
        if self.used_bytes is None:
            return None
        return max(0, self.quota_bytes - self.used_bytes)


@dataclass(frozen=True, kw_only=True)
class PoolUsageRowDto:
    """One user's total on a pool over a period, as reported by the panel."""

    user_remna_id: int
    total_bytes: int


@dataclass(frozen=True, kw_only=True)
class PoolNodeDto:
    """A node reachable through a pool's squad — shown when picking/reviewing a pool."""

    uuid: UUID
    name: str
    country_code: str = ""


@dataclass(frozen=True, kw_only=True)
class MeteringTargetDto:
    """A subscription that is subject to one pool, resolved for the metering pass."""

    usage: SubscriptionPoolUsageDto
    subscription_id: int
    user_id: int
    user_remna_id: int
    quota_bytes: int
    reset_strategy: TrafficLimitStrategy
    subscription_created_at: datetime
    plan_internal_squads: list[UUID] = field(default_factory=list)
