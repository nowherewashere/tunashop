import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from loguru import logger

from src.application.common import Interactor, Remnawave
from src.application.common.dao import BroadcastDao, SubscriptionDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.core.constants import (
    TRIAL_BONUS_DAYS,
    TRIAL_BONUS_LOCK_WAIT_SECONDS,
    TRIAL_BONUS_PANEL_WAIT_SECONDS,
)
from src.core.enums import SubscriptionStatus, TrialBonusResult
from src.core.utils.time import datetime_now

# A trial that is switched off (channel guard) or out of traffic gains nothing from an
# extra day — and pushing it through the panel would flip it back on. Only these two
# reach the reward: a running trial, or one that simply ran out.
_CLAIMABLE_STATUSES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED)


@dataclass(frozen=True)
class ClaimTrialBonusDto:
    task_id: UUID


@dataclass(frozen=True)
class TrialBonusOutcome:
    result: TrialBonusResult
    days: int = TRIAL_BONUS_DAYS
    expire_at: Optional[datetime] = None


class ClaimTrialBonus(Interactor[ClaimTrialBonusDto, TrialBonusOutcome]):
    """Redeem the "+1 trial day" button carried by a broadcast.

    A running trial is pushed one day further; an expired one restarts from the press,
    which is the same arithmetic — `max(expire_at, now) + 1 day`.
    """

    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        broadcast_dao: BroadcastDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
    ) -> None:
        self.uow = uow
        self.broadcast_dao = broadcast_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: ClaimTrialBonusDto) -> TrialBonusOutcome:
        task_id = data.task_id

        message = await self.broadcast_dao.get_message_for_user(task_id, actor.id)
        if not message:
            # Not a recipient of this broadcast — a forwarded copy, an admin preview, or
            # a broadcast the weekly cleanup has already removed.
            logger.info(f"{actor.log} Pressed the trial bonus of broadcast '{task_id}' uninvited")
            return TrialBonusOutcome(TrialBonusResult.UNAVAILABLE)

        if message.bonus_claimed_at:
            return TrialBonusOutcome(TrialBonusResult.ALREADY_CLAIMED)

        subscription = await self.subscription_dao.get_current(actor.id)
        if not subscription or not subscription.is_trial:
            logger.info(f"{actor.log} Has no trial to extend with the broadcast bonus")
            return TrialBonusOutcome(TrialBonusResult.NOT_ELIGIBLE)

        if subscription.status not in _CLAIMABLE_STATUSES:
            logger.info(
                f"{actor.log} Trial is '{subscription.status}', not claimable for the bonus"
            )
            return TrialBonusOutcome(TrialBonusResult.NOT_ELIGIBLE)

        async with self.uow:
            # The claim below locks its ledger row until this transaction ends, and the
            # panel call sits inside that window. Capped so a rival press for the same
            # row gives up rather than holding a pooled connection through the panel.
            await self.uow.set_lock_timeout(TRIAL_BONUS_LOCK_WAIT_SECONDS)

            # Taking the claim first is what makes a double press (or two racing ones)
            # harmless: the loser matches no row here and leaves with nothing granted.
            if not await self.broadcast_dao.claim_message_bonus(task_id, actor.id):
                await self.uow.rollback()
                return TrialBonusOutcome(TrialBonusResult.ALREADY_CLAIMED)

            # An expired trial restarts from now; a live one keeps its remaining time.
            new_expire = max(subscription.expire_at, datetime_now()) + timedelta(
                days=TRIAL_BONUS_DAYS
            )
            subscription.expire_at = new_expire

            # Inside the transaction on purpose: a panel failure raises, the UoW rolls
            # back, and the claim is released so the person can press again. The other
            # half of that bargain is this timeout — the lock cap above only governs
            # who waits, so without a cap on the wait itself a panel that never answers
            # would keep the row (and the connection) for the client's own 25s read
            # timeout. Timing out raises, which takes the same rollback path.
            async with asyncio.timeout(TRIAL_BONUS_PANEL_WAIT_SECONDS):
                updated = await self.remnawave.update_user(
                    user=actor,
                    user_id=subscription.user_remna_id,
                    subscription=subscription,
                )
            # A revived trial comes back ACTIVE from the panel; without this the row
            # would keep saying EXPIRED until the next sync.
            subscription.status = SubscriptionStatus(updated.status)

            await self.subscription_dao.update(subscription)
            await self.uow.commit()

        logger.info(
            f"{actor.log} Claimed '{TRIAL_BONUS_DAYS}' trial day(s) from broadcast '{task_id}', "
            f"trial now expires at '{new_expire}'"
        )
        return TrialBonusOutcome(TrialBonusResult.GRANTED, expire_at=new_expire)
