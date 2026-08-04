from datetime import timedelta

from loguru import logger

from src.application.common.dao import LifecycleFollowupDao
from src.application.common.uow import UnitOfWork
from src.application.events.user import SubscriptionExpiredEvent
from src.core.utils.time import datetime_now
from src.infrastructure.database.models.lifecycle_followup import CHAIN_WINBACK
from src.infrastructure.services.event_bus import on_event

# Win-back touches after churn (spec §6 chain E): soft returns at +3d and +2w.
_WINBACK_STEPS: tuple[tuple[str, timedelta], ...] = (
    ("e_3d", timedelta(days=3)),
    ("e_2w", timedelta(days=14)),
)


class LifecycleFollowupHandler:
    """Arms the win-back chain (E) when a subscription expires.

    Additive listener on the existing ``SubscriptionExpiredEvent``. The sweeper
    re-validates state before sending, so a user who resubscribes before a touch
    fires simply has that touch cancelled — no explicit cancel event needed.
    """

    def __init__(self, uow: UnitOfWork, followup_dao: LifecycleFollowupDao) -> None:
        self.uow = uow
        self.followup_dao = followup_dao

    @on_event(SubscriptionExpiredEvent)
    async def on_subscription_expired(self, event: SubscriptionExpiredEvent) -> None:
        telegram_id = event.user.telegram_id
        if telegram_id is None:
            return

        now = datetime_now()
        async with self.uow:
            for step, offset in _WINBACK_STEPS:
                await self.followup_dao.schedule(
                    telegram_id=telegram_id,
                    chain=CHAIN_WINBACK,
                    step=step,
                    fire_at=now + offset,
                )
            await self.uow.commit()

        logger.debug(f"Armed win-back followups for user '{telegram_id}'")
