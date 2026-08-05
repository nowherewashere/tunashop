from typing import Any, Optional, cast
from uuid import UUID

from loguru import logger
from redis.asyncio import Redis
from remnapy.enums.users import TrafficLimitStrategy
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import TrafficPoolDao
from src.application.dto import MeteringTargetDto, SubscriptionPoolUsageDto, TrafficPoolDto
from src.core.constants import PUBLIC_LANDING_PLANS_CACHE_KEY
from src.core.enums import SubscriptionStatus
from src.core.utils.converters import gb_to_bytes
from src.core.utils.time import datetime_now
from src.infrastructure.database.models import (
    PlanTrafficPool,
    Subscription,
    SubscriptionPoolUsage,
    TrafficPool,
    User,
)


def _to_pool_dto(row: TrafficPool) -> TrafficPoolDto:
    return TrafficPoolDto(
        id=row.id,
        name=row.name,
        internal_squad_uuid=row.internal_squad_uuid,
        is_active=row.is_active,
        order_index=row.order_index,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_usage_dto(row: SubscriptionPoolUsage) -> SubscriptionPoolUsageDto:
    return SubscriptionPoolUsageDto(
        id=row.id,
        subscription_id=row.subscription_id,
        pool_id=row.pool_id,
        period_start=row.period_start,
        used_bytes=row.used_bytes,
        is_exhausted=row.is_exhausted,
        exhausted_at=row.exhausted_at,
        warned_at=row.warned_at,
        metered_at=row.metered_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class TrafficPoolDaoImpl(TrafficPoolDao):
    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self.session = session
        self.redis = redis

    async def get_all(self) -> list[TrafficPoolDto]:
        stmt = select(TrafficPool).order_by(TrafficPool.order_index.asc(), TrafficPool.id.asc())
        rows = (await self.session.scalars(stmt)).all()
        return [_to_pool_dto(row) for row in rows]

    async def get_active(self) -> list[TrafficPoolDto]:
        stmt = (
            select(TrafficPool)
            .where(TrafficPool.is_active.is_(True))
            .order_by(TrafficPool.order_index.asc(), TrafficPool.id.asc())
        )
        rows = (await self.session.scalars(stmt)).all()
        return [_to_pool_dto(row) for row in rows]

    async def get_by_id(self, pool_id: int) -> Optional[TrafficPoolDto]:
        row = await self.session.get(TrafficPool, pool_id)
        return _to_pool_dto(row) if row else None

    async def create(self, pool: TrafficPoolDto) -> TrafficPoolDto:
        row = TrafficPool(
            name=pool.name,
            internal_squad_uuid=pool.internal_squad_uuid,
            is_active=pool.is_active,
            order_index=pool.order_index,
        )
        self.session.add(row)
        await self.session.flush()
        await self._invalidate_landing_plans_cache()

        logger.debug(f"Created traffic pool '{row.name}' on squad '{row.internal_squad_uuid}'")
        return _to_pool_dto(row)

    async def update(self, pool: TrafficPoolDto) -> Optional[TrafficPoolDto]:
        row = await self.session.get(TrafficPool, pool.id)
        if not row:
            logger.warning(f"Traffic pool '{pool.id}' not found for update")
            return None

        row.name = pool.name
        row.internal_squad_uuid = pool.internal_squad_uuid
        row.is_active = pool.is_active
        row.order_index = pool.order_index

        await self.session.flush()
        await self._invalidate_landing_plans_cache()
        return _to_pool_dto(row)

    async def delete(self, pool_id: int) -> bool:
        stmt = delete(TrafficPool).where(TrafficPool.id == pool_id).returning(TrafficPool.id)
        deleted = (await self.session.execute(stmt)).scalar_one_or_none()
        if deleted:
            await self._invalidate_landing_plans_cache()
            logger.debug(f"Deleted traffic pool '{pool_id}' (plan quotas cascade)")
            return True
        return False

    async def count_plans_using(self, pool_id: int) -> int:
        stmt = select(func.count(PlanTrafficPool.id)).where(PlanTrafficPool.pool_id == pool_id)
        return await self.session.scalar(stmt) or 0

    # --- accounting windows -------------------------------------------------

    async def get_usage(
        self, subscription_id: int, pool_id: int
    ) -> Optional[SubscriptionPoolUsageDto]:
        stmt = select(SubscriptionPoolUsage).where(
            SubscriptionPoolUsage.subscription_id == subscription_id,
            SubscriptionPoolUsage.pool_id == pool_id,
        )
        row = await self.session.scalar(stmt)
        return _to_usage_dto(row) if row else None

    async def list_usage(self, subscription_id: int) -> list[SubscriptionPoolUsageDto]:
        stmt = select(SubscriptionPoolUsage).where(
            SubscriptionPoolUsage.subscription_id == subscription_id
        )
        rows = (await self.session.scalars(stmt)).all()
        return [_to_usage_dto(row) for row in rows]

    async def upsert_usage(self, usage: SubscriptionPoolUsageDto) -> SubscriptionPoolUsageDto:
        # ON CONFLICT on the (subscription, pool) unique key: the metering pass and a
        # concurrent purchase can both open the same window, and the loser must update
        # rather than blow up the whole cycle on an IntegrityError.
        values = {
            "subscription_id": usage.subscription_id,
            "pool_id": usage.pool_id,
            "period_start": usage.period_start,
            "used_bytes": usage.used_bytes,
            "is_exhausted": usage.is_exhausted,
            "exhausted_at": usage.exhausted_at,
            "warned_at": usage.warned_at,
            "metered_at": usage.metered_at,
        }
        stmt = (
            pg_insert(SubscriptionPoolUsage)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_subscription_pool_usage_sub_pool",
                set_={k: v for k, v in values.items() if k not in ("subscription_id", "pool_id")},
            )
            .returning(SubscriptionPoolUsage)
        )
        row = await self.session.scalar(stmt)
        return _to_usage_dto(cast(SubscriptionPoolUsage, row))

    async def delete_usage(self, subscription_id: int, pool_ids: list[int]) -> None:
        if not pool_ids:
            return
        await self.session.execute(
            delete(SubscriptionPoolUsage).where(
                SubscriptionPoolUsage.subscription_id == subscription_id,
                SubscriptionPoolUsage.pool_id.in_(pool_ids),
            )
        )

    async def carry_over_usage(self, from_subscription_id: int, to_subscription_id: int) -> int:
        """Move accounting windows onto the subscription row that replaces another.

        A plan change retires the old subscription and writes a new one. Without this
        the new row would start with empty windows, so switching plans would hand back
        an exhausted premium pool — a free quota reset, farmable on demand. The panel's
        own usage history is per user and untouched by the swap, so carrying the window
        over is also the only way the two stay consistent.

        Rows already present on the target win (the target is the live row); the rest
        are repointed.
        """
        existing = select(SubscriptionPoolUsage.pool_id).where(
            SubscriptionPoolUsage.subscription_id == to_subscription_id
        )
        await self.session.execute(
            delete(SubscriptionPoolUsage).where(
                SubscriptionPoolUsage.subscription_id == from_subscription_id,
                SubscriptionPoolUsage.pool_id.in_(existing),
            )
        )
        moved = len(
            (
                await self.session.scalars(
                    update(SubscriptionPoolUsage)
                    .where(SubscriptionPoolUsage.subscription_id == from_subscription_id)
                    .values(subscription_id=to_subscription_id)
                    .returning(SubscriptionPoolUsage.id)
                )
            ).all()
        )
        if moved:
            logger.debug(
                f"Carried over '{moved}' pool usage windows from subscription "
                f"'{from_subscription_id}' to '{to_subscription_id}'"
            )
        return moved

    async def get_metering_targets(self, pool_id: int) -> list[MeteringTargetDto]:
        """Every live subscription whose snapshot meters ``pool_id``.

        Reads the quota from ``plan_snapshot`` (frozen at purchase, so a later plan
        edit never re-prices an existing subscription) and joins the existing window,
        which may still be absent for a subscription bought before the pool existed.
        """
        stmt = (
            select(Subscription, SubscriptionPoolUsage)
            .join(User, User.current_subscription_id == Subscription.id)
            .outerjoin(
                SubscriptionPoolUsage,
                (SubscriptionPoolUsage.subscription_id == Subscription.id)
                & (SubscriptionPoolUsage.pool_id == pool_id),
            )
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                # Checked alongside the status because the stored one only flips to
                # EXPIRED on that user's next panel sync, exactly as UserDao does for
                # paid audiences. A lapsed subscription left in here is not just noise:
                # both verdicts push `expire_at` back to the panel, which rejects a date
                # in the past, so the pass would fail on it again every single tick.
                Subscription.expire_at > datetime_now(),
                # jsonb_array_length() raises on a non-array, and this query runs on
                # every cron tick over every live subscription — one hand-edited or
                # legacy snapshot would take the whole pool's pass down. A missing key
                # is already safe (-> yields SQL NULL); the typeof guard covers the rest.
                func.jsonb_typeof(Subscription.plan_snapshot["traffic_pools"]) == "array",
                func.jsonb_array_length(Subscription.plan_snapshot["traffic_pools"]) > 0,
            )
        )
        rows = (await self.session.execute(stmt)).all()

        targets: list[MeteringTargetDto] = []
        for subscription, usage in rows:
            quota = _find_snapshot_quota(subscription.plan_snapshot, pool_id)
            if quota is None or quota[0] <= 0:
                continue

            quota_gb, strategy = quota
            targets.append(
                MeteringTargetDto(
                    usage=_to_usage_dto(usage)
                    if usage
                    else SubscriptionPoolUsageDto(
                        subscription_id=subscription.id,
                        pool_id=pool_id,
                        # Placeholder — the caller derives the real window from the
                        # strategy before writing anything.
                        period_start=subscription.created_at,
                    ),
                    subscription_id=subscription.id,
                    user_id=subscription.user_id,
                    user_remna_id=subscription.user_remna_id,
                    quota_bytes=gb_to_bytes(quota_gb),
                    reset_strategy=strategy,
                    subscription_created_at=subscription.created_at,
                    plan_internal_squads=_snapshot_squads(subscription.plan_snapshot),
                )
            )

        logger.debug(f"Resolved '{len(targets)}' metering targets for pool '{pool_id}'")
        return targets

    async def _invalidate_landing_plans_cache(self) -> None:
        # Pool names/quotas are rendered on the public plan cards, which the landing
        # endpoint caches — drop it so an edit shows on the site's next request.
        await self.redis.delete(PUBLIC_LANDING_PLANS_CACHE_KEY)


def _find_snapshot_quota(
    snapshot: dict[str, Any], pool_id: int
) -> Optional[tuple[int, TrafficLimitStrategy]]:
    """Read one pool's frozen quota out of a ``plan_snapshot`` JSON blob.

    Tolerant by design: snapshots written before the feature have no key at all, and
    an unknown strategy string (a panel enum we no longer ship) degrades to MONTH
    rather than taking the whole metering pass down.
    """
    for entry in snapshot.get("traffic_pools") or []:
        if not isinstance(entry, dict) or entry.get("pool_id") != pool_id:
            continue

        try:
            strategy = TrafficLimitStrategy(str(entry.get("reset_strategy")))
        except ValueError:
            logger.warning(
                f"Unknown pool reset strategy '{entry.get('reset_strategy')}' "
                f"in snapshot for pool '{pool_id}', falling back to MONTH"
            )
            strategy = TrafficLimitStrategy.MONTH

        return int(entry.get("quota_gb") or 0), strategy
    return None


def _snapshot_squads(snapshot: dict[str, Any]) -> list[UUID]:
    squads: list[UUID] = []
    for raw in snapshot.get("internal_squads") or []:
        try:
            squads.append(raw if isinstance(raw, UUID) else UUID(str(raw)))
        except (ValueError, AttributeError, TypeError):
            continue
    return squads
