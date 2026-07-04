from dataclasses import dataclass

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import OnboardingNudgeDao
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto


@dataclass(frozen=True)
class CancelOnboardingNudgesDto:
    telegram_id: int


class CancelOnboardingNudges(Interactor[CancelOnboardingNudgesDto, None]):
    """Cancel every pending nudge for a user — the completion signal (reaching the
    funnel's success screen) and the stop-on-block path both go through here."""

    required_permission = None

    def __init__(self, uow: UnitOfWork, nudge_dao: OnboardingNudgeDao) -> None:
        self.uow = uow
        self.nudge_dao = nudge_dao

    async def _execute(self, actor: UserDto, data: CancelOnboardingNudgesDto) -> None:
        async with self.uow:
            await self.nudge_dao.cancel_pending(data.telegram_id)
            await self.uow.commit()

        logger.debug(f"Cancelled pending onboarding nudges for user '{data.telegram_id}'")
