from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import SettingsDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto


class ToggleReferralSystem(Interactor[None, bool]):
    """The only referral setting that still drives behaviour.

    The economic parameters (rate, payout floor, Stars) are env-driven — see
    ``ReferralConfig`` / ``PayoutConfig`` / ``StarsConfig``. The old level / reward-type
    / accrual-strategy editors were dropped with the points→money rework: nothing read
    what they wrote.
    """

    required_permission = Permission.SETTINGS_REFERRAL

    def __init__(self, uow: UnitOfWork, settings_dao: SettingsDao) -> None:
        self.uow = uow
        self.settings_dao = settings_dao

    async def _execute(self, actor: UserDto, data: None) -> bool:
        async with self.uow:
            settings = await self.settings_dao.get()
            old_status = settings.referral.enable
            settings.referral.enable = not old_status
            await self.settings_dao.update(settings)
            await self.uow.commit()

        logger.info(
            f"{actor.log} Toggled referral system "
            f"from '{old_status}' to '{settings.referral.enable}'"
        )
        return settings.referral.enable
