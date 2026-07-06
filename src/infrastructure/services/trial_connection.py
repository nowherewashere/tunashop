from datetime import datetime, timedelta

from loguru import logger

from src.application.common.dao import (
    LifecycleFollowupDao,
    OnboardingNudgeDao,
    SubscriptionDao,
    UserConnectionStateDao,
)
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.events.system import UserFirstConnectionEvent
from src.core.utils.time import datetime_now
from src.infrastructure.database.models.lifecycle_followup import CHAIN_TRIAL_ENDING
from src.infrastructure.services.event_bus import on_event

# Post-connect proactive followups armed at first connection (spec §6).
_TRIAL_ENDING_LEAD = timedelta(hours=3)  # chain C: nudge 3h before the trial ends


class TrialConnectionHandler:
    """Additive listener on the first-connection event (spec §3, §4.1).

    On a user's first successful connection it:
      1. records the local ``connected_once`` milestone (drives the hub's
         Подключиться↔Открыть инструкции switch and cancels the not-connected
         nudge chain — a real connection is the "it works" signal), and
      2. restarts the trial clock so the countdown runs from first connection
         instead of from activation.

    Purely additive: it hooks the already-published ``UserFirstConnectionEvent``
    and never touches the trial-activation flow or the shared ``User`` model.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        remnawave: Remnawave,
        subscription_dao: SubscriptionDao,
        conn_state_dao: UserConnectionStateDao,
        nudge_dao: OnboardingNudgeDao,
        followup_dao: LifecycleFollowupDao,
    ) -> None:
        self.uow = uow
        self.remnawave = remnawave
        self.subscription_dao = subscription_dao
        self.conn_state_dao = conn_state_dao
        self.nudge_dao = nudge_dao
        self.followup_dao = followup_dao

    @on_event(UserFirstConnectionEvent)
    async def on_first_connection(self, event: UserFirstConnectionEvent) -> None:
        telegram_id = event.telegram_id
        if telegram_id is None:
            return

        now = datetime_now()
        async with self.uow:
            await self.conn_state_dao.mark_connected(telegram_id, now)
            await self.nudge_dao.cancel_pending(telegram_id)

            if event.is_trial:
                await self._restart_trial_clock(event, telegram_id, now)

            await self.uow.commit()

    async def _restart_trial_clock(
        self,
        event: UserFirstConnectionEvent,
        telegram_id: int,
        now: datetime,
    ) -> None:
        subscription = await self.subscription_dao.get_by_remna_id(event.subscription_id)
        if not subscription or not subscription.created_at:
            return

        # Preserve the exact granted window (24h base / 72h referred / whatever the
        # trial plan carried) — no separate config needed.
        granted = subscription.expire_at - subscription.created_at
        if granted.total_seconds() <= 0:
            return

        # Claim the one-time restart; if another first-connection event already did
        # it, do nothing (idempotent).
        if not await self.conn_state_dao.try_mark_trial_restarted(telegram_id, now):
            return

        new_expire = now + granted
        await self.remnawave.set_user_expire(event.subscription_id, new_expire)
        subscription.expire_at = new_expire
        await self.subscription_dao.update(subscription)
        logger.info(
            f"Restarted trial clock for '{telegram_id}' to '{new_expire.isoformat()}' "
            f"(granted window {granted})"
        )

        # Arm the post-connect proactive chain against the fresh clock (spec §6 C).
        trial_ending_at = new_expire - _TRIAL_ENDING_LEAD
        if trial_ending_at > now:
            await self.followup_dao.schedule(
                telegram_id, CHAIN_TRIAL_ENDING, "c_3h", trial_ending_at
            )
