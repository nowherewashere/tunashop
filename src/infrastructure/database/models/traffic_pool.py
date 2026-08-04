from datetime import datetime
from typing import Optional
from uuid import UUID

from remnapy.enums.users import TrafficLimitStrategy
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin

# ---------------------------------------------------------------------------
# Traffic pools (additive fork feature).
#
# Product shape: traffic is unlimited on ordinary locations, but a *pool* of
# premium locations carries a quota that differs per plan.
#
# The panel cannot express this. It has exactly one traffic limit per user, it is
# global, and exhausting it moves the user to LIMITED on every location; there is
# no limit on a squad, a node or an inbound in any version. So the global
# ``trafficLimitBytes`` is kept at 0 and the quota is metered and enforced here.
#
# Two hard constraints shape the schema:
#   * Usage can only be split per NODE — Xray exposes ``user>>>traffic`` and
#     ``inbound>>>traffic`` but no "user x inbound" counter, and the per-node split
#     exists only because each node is its own Xray instance. A metered location
#     therefore has to be its own node.
#   * The unit the panel can report on is an internal squad (its bandwidth-stats
#     endpoints are scoped to the nodes reachable through a squad's inbounds), so a
#     pool is exactly one internal squad holding premium-node inbounds only.
# ---------------------------------------------------------------------------


class TrafficPool(BaseSql, TimestampMixin):
    """A metered group of premium locations, backed by one internal squad."""

    __tablename__ = "traffic_pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # Both the squad whose nodes are metered and the squad withdrawn when the quota
    # runs out — one column, so a pool can never meter one thing and cut another.
    internal_squad_uuid: Mapped[UUID] = mapped_column(unique=True)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    order_index: Mapped[int] = mapped_column(default=0, server_default="0")


class PlanTrafficPool(BaseSql):
    """The quota a given plan grants on a given pool, plus its reset period.

    Absent row = the plan does not meter that pool: if the pool's squad is among the
    plan's internal squads the user simply gets it unmetered, otherwise they never
    see it at all.
    """

    __tablename__ = "plan_traffic_pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    pool_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("traffic_pools.id", ondelete="CASCADE"), index=True
    )
    quota_gb: Mapped[int]
    # Per-plan reset period, reusing the panel's own vocabulary so the wording in the
    # dashboard matches the traffic-limit strategy admins already know.
    reset_strategy: Mapped[TrafficLimitStrategy] = mapped_column(
        default=TrafficLimitStrategy.MONTH, server_default="MONTH"
    )

    __table_args__ = (
        UniqueConstraint("plan_id", "pool_id", name="uq_plan_traffic_pools_plan_pool"),
    )


class SubscriptionPoolUsage(BaseSql, TimestampMixin):
    """One subscription's accounting window on one pool.

    Opened when the subscription first receives the pool and then rolled forward in
    place: when ``period_start`` moves, counters and notices clear and the squad is
    handed back. Keyed by subscription (not user) so it travels with the subscription
    — an account merge repoints ``subscriptions.user_id``, and a plan change, which
    retires the old subscription row and writes a new one, carries the rows over
    explicitly. Both matter: a fresh window would otherwise be a free quota reset.
    """

    __tablename__ = "subscription_pool_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subscriptions.id", ondelete="CASCADE")
    )
    pool_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("traffic_pools.id", ondelete="CASCADE")
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Bytes seen by the last metering pass. NULL = "below the warning threshold": the
    # pass filters server-side (minTotalBytes), so under it nothing exact is known.
    used_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_exhausted: Mapped[bool] = mapped_column(default=False, server_default="false")
    exhausted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Stamped once per window so the "почти всё" notice cannot repeat every tick.
    warned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "pool_id", name="uq_subscription_pool_usage_sub_pool"
        ),
        Index("ix_subscription_pool_usage_pool_id", "pool_id"),
    )
