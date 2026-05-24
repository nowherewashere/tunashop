from dataclasses import dataclass

from loguru import logger
from remnapy import RemnawaveSDK
from remnapy.models import DeleteUserAllHwidDeviceRequestDto

from src.application.common import Interactor
from src.application.common.dao import SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.dto import UserDto


@dataclass(frozen=True)
class DeleteUserDeviceDto:
    user_id: int
    hwid: str


class DeleteUserDevice(Interactor[DeleteUserDeviceDto, bool]):
    required_permission = Permission.PUBLIC

    def __init__(self, subscription_dao: SubscriptionDao, remnawave: Remnawave) -> None:
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: DeleteUserDeviceDto) -> bool:
        current_subscription = await self.subscription_dao.get_current(data.user_id)

        if not current_subscription:
            raise ValueError(f"Subscription for user_id '{data.user_id}' not found")

        remaining_devices = await self.remnawave.delete_device(
            current_subscription.user_remna_id,
            data.hwid,
        )

        logger.info(f"{actor.log} Deleted device '{data.hwid}' for user_id '{data.user_id}'")
        return bool(remaining_devices)


class DeleteUserAllDevices(Interactor[None, None]):
    required_permission = Permission.PUBLIC

    def __init__(self, subscription_dao: SubscriptionDao, remnawave_sdk: RemnawaveSDK) -> None:
        self.subscription_dao = subscription_dao
        self.remnawave_sdk = remnawave_sdk

    async def _execute(self, actor: UserDto, data: None) -> None:
        current_subscription = await self.subscription_dao.get_current(actor.id)

        if not current_subscription:
            raise ValueError(
                f"User '{actor.remna_name}' has no active subscription or device limit unlimited"
            )

        result = await self.remnawave_sdk.hwid.delete_all_hwid_user(
            DeleteUserAllHwidDeviceRequestDto(user_uuid=current_subscription.user_remna_id)
        )

        logger.info(f"{actor.log} Deleted all devices ({result.total})")


class ResetUserTraffic(Interactor[int, None]):
    required_permission = Permission.USER_EDITOR

    def __init__(
        self,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave_sdk: RemnawaveSDK,
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave_sdk = remnawave_sdk

    async def _execute(self, actor: UserDto, user_id: int) -> None:
        target_user = await self.user_dao.get_by_id(user_id)
        if not target_user:
            raise ValueError(f"User '{user_id}' not found")

        subscription = await self.subscription_dao.get_current(target_user.id)
        if not subscription:
            raise ValueError(f"Subscription for user '{target_user.remna_name}' not found")

        try:
            await self.remnawave_sdk.users.reset_user_traffic(subscription.user_remna_id)
        except Exception as e:
            logger.error(
                f"Failed to reset traffic in Remnawave for user '{target_user.remna_name}': {e}"
            )
            raise

        logger.info(f"{actor.log} Reset traffic for user '{target_user.remna_name}'")


class ReissueSubscription(Interactor[None, None]):
    required_permission = Permission.PUBLIC

    def __init__(self, subscription_dao: SubscriptionDao, remnawave: Remnawave) -> None:
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: None) -> None:
        current_subscription = await self.subscription_dao.get_current(actor.id)

        if not current_subscription:
            raise ValueError(f"No active subscription for user '{actor.remna_name}'")

        await self.remnawave.revoke_subscription(current_subscription.user_remna_id)

        logger.info(f"{actor.log} Reissued subscription")


class ReissueUserSubscription(Interactor[int, None]):
    required_permission = Permission.USER_EDITOR

    def __init__(
        self, user_dao: UserDao, subscription_dao: SubscriptionDao, remnawave: Remnawave
    ) -> None:
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, user_id: int) -> None:
        target_user = await self.user_dao.get_by_id(user_id)
        if not target_user:
            raise ValueError(f"User '{user_id}' not found")

        current_subscription = await self.subscription_dao.get_current(target_user.id)

        if not current_subscription:
            raise ValueError(f"No active subscription for user '{target_user.remna_name}'")

        await self.remnawave.revoke_subscription(current_subscription.user_remna_id)

        logger.info(f"{actor.log} Reissued subscription for user '{target_user.remna_name}'")
