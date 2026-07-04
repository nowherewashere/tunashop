from dataclasses import dataclass
from datetime import timedelta

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import OnboardingNudgeDao
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.core.config import AppConfig
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class ScheduleOnboardingNudgesDto:
    telegram_id: int


class ScheduleOnboardingNudges(Interactor[ScheduleOnboardingNudgesDto, None]):
    """Arm the pre-connect nudge chain for a user who entered the funnel.

    Idempotent per user (the DAO skips steps that already exist), so re-entering
    the funnel never duplicates or resets the chain.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        nudge_dao: OnboardingNudgeDao,
        config: AppConfig,
    ) -> None:
        self.uow = uow
        self.nudge_dao = nudge_dao
        self.config = config

    async def _execute(self, actor: UserDto, data: ScheduleOnboardingNudgesDto) -> None:
        delays = self.config.onboarding.nudge_delays
        if not delays:
            return

        now = datetime_now()
        async with self.uow:
            for index, hours in enumerate(delays, start=1):
                await self.nudge_dao.schedule(
                    telegram_id=data.telegram_id,
                    step=f"nudge_{index}",
                    fire_at=now + timedelta(hours=hours),
                )
            await self.uow.commit()

        logger.debug(
            f"Scheduled {len(delays)} onboarding nudge(s) for user '{data.telegram_id}'"
        )
