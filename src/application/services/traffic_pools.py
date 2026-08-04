from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from loguru import logger

from src.application.common import EventPublisher, Remnawave
from src.application.common.dao import SubscriptionDao, TrafficPoolDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import (
    MeteringTargetDto,
    PlanSnapshotDto,
    PoolUsageViewDto,
    SubscriptionDto,
    SubscriptionPoolUsageDto,
    TrafficPoolDto,
    UserDto,
)
from src.application.events import PoolTrafficExhaustedEvent, PoolTrafficWarningEvent
from src.core.config import AppConfig
from src.core.config.traffic_pools import TRAFFIC_POOL_WARN_RATIO
from src.core.constants import POOL_RESET_DATE_FORMAT
from src.core.utils.i18n_helpers import i18n_format_bytes_to_unit
from src.core.utils.time import (
    datetime_now,
    get_traffic_period_end,
    get_traffic_period_start,
)


class TrafficPoolAccessService:
    """Decides which internal squads a subscription may hold right now.

    The panel has no per-squad traffic limit, so "the quota on the premium pool ran
    out" is expressed the only way the panel understands: the pool's squad comes off
    the user. Everything else the plan grants stays untouched — which is the whole
    point of the feature: unlimited elsewhere, metered here.

    This class owns the *bookkeeping* (which squads, which windows). The decision of
    when to cut belongs to :class:`TrafficPoolMeteringService`.
    """

    def __init__(
        self,
        config: AppConfig,
        traffic_pool_dao: TrafficPoolDao,
        remnawave: Remnawave,
    ) -> None:
        self.config = config
        self.traffic_pool_dao = traffic_pool_dao
        self.remnawave = remnawave

    @property
    def is_enabled(self) -> bool:
        return self.config.traffic_pools.enabled

    async def effective_squads(
        self,
        plan_squads: list[UUID],
        usage_subscription_id: Optional[int],
    ) -> list[UUID]:
        """The plan's squads minus the pools this subscription has already spent.

        Called from every path that assigns ``subscription.internal_squads`` from a
        plan. Without it a renewal, a promo reward or an admin plan grant would hand
        an exhausted pool straight back, because each of those rewrites the squad
        list wholesale from the plan.

        A subscription with no windows yet (a brand-new purchase) gets the plan's
        list verbatim — as does everyone while the feature is switched off.
        """
        if not self.is_enabled or usage_subscription_id is None:
            return list(plan_squads)

        exhausted = await self._exhausted_squads(usage_subscription_id)
        if not exhausted:
            return list(plan_squads)

        kept = [squad for squad in plan_squads if squad not in exhausted]
        logger.debug(
            f"Subscription '{usage_subscription_id}': withheld "
            f"'{len(plan_squads) - len(kept)}' exhausted pool squad(s) from the plan's list"
        )
        return kept

    async def reconcile_windows(
        self,
        subscription_id: int,
        plan_snapshot: PlanSnapshotDto,
    ) -> None:
        """Close windows for pools the (new) plan does not meter.

        A plan change can move the user onto a plan that grants the same pool with no
        quota at all — a leftover window must not keep cutting a squad the new plan
        gives away freely. Windows for pools the new plan *does* meter are deliberately
        left in place: they carry the period the user is already inside, so switching
        plans is never a free quota reset. Missing windows are opened by the metering
        pass, which is the only place that knows the real usage behind them.
        """
        if not self.is_enabled:
            return

        metered = {quota.pool_id for quota in plan_snapshot.traffic_pools if quota.quota_gb > 0}
        stale = [
            usage.pool_id
            for usage in await self.traffic_pool_dao.list_usage(subscription_id)
            if usage.pool_id not in metered
        ]
        if stale:
            await self.traffic_pool_dao.delete_usage(subscription_id, stale)
            logger.info(
                f"Subscription '{subscription_id}': closed '{len(stale)}' pool window(s) "
                f"the new plan no longer meters"
            )

    async def carry_over(self, from_subscription_id: int, to_subscription_id: int) -> None:
        """Move windows onto the subscription row that replaced another (plan change)."""
        if not self.is_enabled:
            return
        await self.traffic_pool_dao.carry_over_usage(from_subscription_id, to_subscription_id)

    async def build_views(
        self,
        subscription: SubscriptionDto,
        *,
        with_live_usage: bool = True,
    ) -> list[PoolUsageViewDto]:
        """Render-ready state of every pool this subscription is metered on.

        ``used_bytes`` is asked of the panel per user: the metering sweep is
        threshold-filtered and therefore blind below the warning floor, so the stored
        value cannot answer "how much have I used" on its own. If the panel is
        unreachable the field stays ``None`` and the surface shows "unknown" instead
        of a fabricated zero.
        """
        if not self.is_enabled or not subscription.plan_snapshot.traffic_pools:
            return []

        pools = {pool.id: pool for pool in await self.traffic_pool_dao.get_all()}
        windows = {u.pool_id: u for u in await self.traffic_pool_dao.list_usage(subscription.id)}
        created_at = subscription.created_at or datetime_now()

        views: list[PoolUsageViewDto] = []
        for quota in subscription.plan_snapshot.traffic_pools:
            pool = pools.get(quota.pool_id)
            if pool is None or quota.quota_gb <= 0:
                continue

            window = windows.get(quota.pool_id)
            period_start = (
                window.period_start
                if window
                else get_traffic_period_start(quota.reset_strategy, created_at)
            )
            used = window.used_bytes if window else None

            if with_live_usage:
                try:
                    used = await self.remnawave.get_squad_user_usage(
                        squad_uuid=pool.internal_squad_uuid,
                        user_id=subscription.user_remna_id,
                        start=period_start,
                        end=datetime_now(),
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not read live pool usage for subscription "
                        f"'{subscription.id}' pool '{pool.id}': {e}"
                    )

            views.append(
                PoolUsageViewDto(
                    pool_id=pool.id,
                    name=pool.name,
                    quota_bytes=quota.quota_bytes,
                    used_bytes=used,
                    is_exhausted=bool(window and window.is_exhausted),
                    reset_at=get_traffic_period_end(quota.reset_strategy, created_at),
                )
            )
        return views

    async def _exhausted_squads(self, subscription_id: int) -> set[UUID]:
        windows = [
            usage
            for usage in await self.traffic_pool_dao.list_usage(subscription_id)
            if usage.is_exhausted
        ]
        if not windows:
            return set()

        pools = {pool.id: pool for pool in await self.traffic_pool_dao.get_all()}
        return {
            pools[usage.pool_id].internal_squad_uuid for usage in windows if usage.pool_id in pools
        }


@dataclass
class MeteringReportDto:
    """Counters of one metering pass, for the cron log."""

    pools: int = 0
    checked: int = 0
    exhausted: int = 0
    warned: int = 0
    restored: int = 0
    failed_pools: list[str] = field(default_factory=list)


class TrafficPoolMeteringService:
    """Reads premium usage from the panel and applies the verdict.

    One pass per pool, and inside it one panel request per distinct
    (window start, quota) pair — ``minTotalBytes`` filters server-side, so a single
    request answers both "who is over quota" and "who is close" for the whole pool
    (the floor is the *warning* threshold, not the quota).

    Failure policy: every panel read for a pool happens *before* the first write, so
    an unreachable panel abandons that pool with nothing applied. Access is never cut
    on incomplete data — a missing page reads exactly like "this user used nothing",
    and acting on that would revoke premium from paying users. A failure later in the
    pool (a rejected panel write) simply stops it there; the next tick re-reads
    everything from scratch, since the pass holds no state beyond the windows.
    """

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        traffic_pool_dao: TrafficPoolDao,
        subscription_dao: SubscriptionDao,
        user_dao: UserDao,
        remnawave: Remnawave,
        access: TrafficPoolAccessService,
        event_publisher: EventPublisher,
    ) -> None:
        self.config = config
        self.uow = uow
        self.traffic_pool_dao = traffic_pool_dao
        self.subscription_dao = subscription_dao
        self.user_dao = user_dao
        self.remnawave = remnawave
        self.access = access
        self.event_publisher = event_publisher

    async def run(self) -> MeteringReportDto:
        report = MeteringReportDto()

        if not self.config.traffic_pools.enabled:
            logger.debug("Traffic pools disabled, skipping metering pass")
            return report

        pools = await self.traffic_pool_dao.get_active()
        if not pools:
            logger.debug("No active traffic pools, skipping metering pass")
            return report

        report.pools = len(pools)
        for pool in pools:
            try:
                await self._meter_pool(pool, report)
            except Exception as e:
                report.failed_pools.append(pool.name)
                logger.error(
                    f"Metering pass for pool '{pool.name}' aborted after "
                    f"'{report.checked}' subscription(s): {e}"
                )

        logger.info(
            f"Traffic pool metering: pools={report.pools} checked={report.checked} "
            f"exhausted={report.exhausted} warned={report.warned} "
            f"restored={report.restored} failed={report.failed_pools or '-'}"
        )
        return report

    async def _meter_pool(self, pool: TrafficPoolDto, report: MeteringReportDto) -> None:
        targets = await self.traffic_pool_dao.get_metering_targets(pool.id)
        if not targets:
            return

        now = datetime_now()

        # Read every group from the panel BEFORE touching a single window: if any
        # request fails the exception propagates and this pool is left exactly as it
        # was, which is the whole point of the failure policy.
        usage_by_user = await self._read_usage(pool, targets, now)

        for target in targets:
            rolled = await self._roll_window(pool, target, now, report)
            used = usage_by_user.get(rolled.user_remna_id)
            await self._apply_verdict(pool, rolled, used, now, report)
            report.checked += 1

    async def _read_usage(
        self,
        pool: TrafficPoolDto,
        targets: list[MeteringTargetDto],
        now: datetime,
    ) -> dict[int, int]:
        groups: dict[tuple[datetime, int], set[int]] = {}
        for target in targets:
            period_start = get_traffic_period_start(
                target.reset_strategy, target.subscription_created_at, now
            )
            groups.setdefault((period_start, target.quota_bytes), set()).add(target.user_remna_id)

        usage_by_user: dict[int, int] = {}
        for (period_start, quota_bytes), wanted in groups.items():
            rows = await self.remnawave.get_squad_usage(
                squad_uuid=pool.internal_squad_uuid,
                start=self._bounded_start(period_start, now),
                end=now,
                min_total_bytes=max(1, int(quota_bytes * TRAFFIC_POOL_WARN_RATIO)),
                page_size=self.config.traffic_pools.page_size,
            )
            for row in rows:
                if row.user_remna_id in wanted:
                    # The same panel user can land in two groups only by holding two
                    # subscriptions; keep the larger reading rather than the last one.
                    usage_by_user[row.user_remna_id] = max(
                        usage_by_user.get(row.user_remna_id, 0), row.total_bytes
                    )
        return usage_by_user

    async def _roll_window(
        self,
        pool: TrafficPoolDto,
        target: MeteringTargetDto,
        now: datetime,
        report: MeteringReportDto,
    ) -> MeteringTargetDto:
        """Move the window to the current period, handing the squad back when it moves."""
        period_start = get_traffic_period_start(
            target.reset_strategy, target.subscription_created_at, now
        )
        usage = target.usage

        if usage.id and usage.period_start == period_start:
            return target

        was_exhausted = bool(usage.id) and usage.is_exhausted
        stored = await self._save(
            SubscriptionPoolUsageDto(
                id=usage.id,
                subscription_id=target.subscription_id,
                pool_id=pool.id,
                period_start=period_start,
                used_bytes=None,
                is_exhausted=False,
                exhausted_at=None,
                warned_at=None,
                metered_at=None,
            )
        )

        if was_exhausted and await self._restore_access(pool, target):
            report.restored += 1

        return MeteringTargetDto(
            usage=stored,
            subscription_id=target.subscription_id,
            user_id=target.user_id,
            user_remna_id=target.user_remna_id,
            quota_bytes=target.quota_bytes,
            reset_strategy=target.reset_strategy,
            subscription_created_at=target.subscription_created_at,
            plan_internal_squads=target.plan_internal_squads,
        )

    async def _apply_verdict(
        self,
        pool: TrafficPoolDto,
        target: MeteringTargetDto,
        used: Optional[int],
        now: datetime,
        report: MeteringReportDto,
    ) -> None:
        usage = target.usage
        usage.used_bytes = used
        usage.metered_at = now

        if used is None:
            # Under the warning floor. The exact figure is unknown by construction
            # (the filter is server-side), so record the heartbeat and stop.
            await self._save(usage)
            return

        if used >= target.quota_bytes:
            if usage.is_exhausted:
                await self._save(usage)
                return
            if not await self._cut_access(pool, target):
                # The panel refused the write; leave the window as it was so the next
                # tick retries instead of recording a cut that never happened.
                return
            usage.is_exhausted = True
            usage.exhausted_at = now
            await self._save(usage)
            await self._notify(pool, target, used, exhausted=True)
            report.exhausted += 1
            return

        if usage.warned_at is None:
            usage.warned_at = now
            await self._save(usage)
            await self._notify(pool, target, used, exhausted=False)
            report.warned += 1
            return

        await self._save(usage)

    async def _cut_access(self, pool: TrafficPoolDto, target: MeteringTargetDto) -> bool:
        subscription, user = await self._load(target)
        if not subscription or not user:
            return False

        if pool.internal_squad_uuid not in subscription.internal_squads:
            return True  # already withheld (an admin may have taken it off by hand)

        subscription.internal_squads = [
            squad for squad in subscription.internal_squads if squad != pool.internal_squad_uuid
        ]
        try:
            async with self.uow:
                await self.subscription_dao.update(subscription)
                await self.remnawave.update_user(
                    user=user,
                    user_id=subscription.user_remna_id,
                    subscription=subscription,
                )
                await self.uow.commit()
            # Only after the squad is really gone: an established session keeps
            # flowing through the premium node until the client reconnects, so the
            # cut is not effective without this.
            await self.remnawave.drop_connections(subscription.user_remna_id)
        except Exception as e:
            logger.error(
                f"Failed to withdraw pool '{pool.name}' from subscription "
                f"'{target.subscription_id}': {e}"
            )
            return False

        logger.info(
            f"Pool '{pool.name}' exhausted for subscription '{target.subscription_id}': "
            f"squad withdrawn and connections dropped"
        )
        return True

    async def _restore_access(self, pool: TrafficPoolDto, target: MeteringTargetDto) -> bool:
        subscription, user = await self._load(target)
        if not subscription or not user:
            return False

        # Never widen beyond what the plan pays for: the snapshot is the ceiling, so a
        # pool dropped from the plan mid-period is not handed back by a period roll.
        if pool.internal_squad_uuid not in set(subscription.plan_snapshot.internal_squads):
            logger.debug(
                f"Pool '{pool.name}' is not in the snapshot of subscription "
                f"'{target.subscription_id}', nothing to restore"
            )
            return False

        if pool.internal_squad_uuid in subscription.internal_squads:
            return False

        subscription.internal_squads = [*subscription.internal_squads, pool.internal_squad_uuid]
        try:
            async with self.uow:
                await self.subscription_dao.update(subscription)
                await self.remnawave.update_user(
                    user=user,
                    user_id=subscription.user_remna_id,
                    subscription=subscription,
                )
                await self.uow.commit()
        except Exception as e:
            logger.error(
                f"Failed to restore pool '{pool.name}' for subscription "
                f"'{target.subscription_id}': {e}"
            )
            return False

        logger.info(
            f"Pool '{pool.name}' period rolled for subscription "
            f"'{target.subscription_id}': squad restored"
        )
        return True

    async def _notify(
        self,
        pool: TrafficPoolDto,
        target: MeteringTargetDto,
        used: int,
        *,
        exhausted: bool,
    ) -> None:
        user = await self.user_dao.get_by_id(target.user_id)
        if not user:
            return

        reset_at = get_traffic_period_end(target.reset_strategy, target.subscription_created_at)
        # A plain string (not a datetime) so the FTL only has to interpolate it, and
        # `has_reset` so it can pick the "…до сброса" vs "…до конца подписки" wording.
        reset_label = reset_at.strftime(POOL_RESET_DATE_FORMAT) if reset_at else ""

        if exhausted:
            await self.event_publisher.publish(
                PoolTrafficExhaustedEvent(
                    user=user,
                    pool_name=pool.name,
                    quota=i18n_format_bytes_to_unit(target.quota_bytes),
                    reset_at=reset_label,
                    has_reset=reset_at is not None,
                )
            )
            return

        await self.event_publisher.publish(
            PoolTrafficWarningEvent(
                user=user,
                pool_name=pool.name,
                quota=i18n_format_bytes_to_unit(target.quota_bytes),
                reset_at=reset_label,
                has_reset=reset_at is not None,
                used=i18n_format_bytes_to_unit(used),
                percent=int(used * 100 / target.quota_bytes) if target.quota_bytes else 0,
            )
        )

    async def _load(
        self, target: MeteringTargetDto
    ) -> tuple[Optional[SubscriptionDto], Optional[UserDto]]:
        subscription = await self.subscription_dao.get_by_id(target.subscription_id)
        if not subscription:
            logger.warning(f"Subscription '{target.subscription_id}' vanished mid-pass")
            return None, None

        user = await self.user_dao.get_by_id(target.user_id)
        if not user:
            logger.warning(f"User '{target.user_id}' vanished mid-pass")
            return None, None

        return subscription, user

    def _bounded_start(self, period_start: datetime, now: datetime) -> datetime:
        """Clamp an open-ended window so the panel query stays a bounded date range."""
        floor = now - timedelta(days=self.config.traffic_pools.max_period_days)
        return max(period_start, floor)

    async def _save(self, usage: SubscriptionPoolUsageDto) -> SubscriptionPoolUsageDto:
        async with self.uow:
            stored = await self.traffic_pool_dao.upsert_usage(usage)
            await self.uow.commit()
        return stored
