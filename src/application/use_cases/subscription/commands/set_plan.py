from dataclasses import dataclass

from loguru import logger

from src.application.common import Interactor, Remnawave
from src.application.common.dao import PlanDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, SubscriptionDto, UserDto
from src.application.services import SubscriptionProrationService
from src.core.enums import SubscriptionStatus


@dataclass(frozen=True)
class SetUserSubscriptionDto:
    user_id: int
    plan_id: int
    duration: int


class SetUserSubscription(Interactor[SetUserSubscriptionDto, None]):
    required_permission = Permission.USER_SUBSCRIPTION_EDITOR

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        plan_dao: PlanDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        proration: SubscriptionProrationService,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.plan_dao = plan_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.proration = proration

    async def _execute(self, actor: UserDto, data: SetUserSubscriptionDto) -> None:
        async with self.uow:
            target_user = await self.user_dao.get_by_id(data.user_id)
            if not target_user:
                raise ValueError(f"User '{data.user_id}' not found")

            plan = await self.plan_dao.get_by_id(data.plan_id)
            if not plan:
                raise ValueError(f"Plan '{data.plan_id}' not found")

            plan_snapshot = PlanSnapshotDto.from_plan(plan, data.duration)
            subscription = await self.subscription_dao.get_current(target_user.id)

            if subscription:
                # Admin grant carries no payment, so there is no monetary basis for
                # value-proration: the service preserves the user's remaining days on
                # top of the new duration instead of wiping them. Push the computed
                # expiry via subscription=... (plan=... would reset it to now+duration).
                change = self.proration.compute_change_expiry(
                    current=subscription,
                    new_duration=plan_snapshot.duration,
                    new_price=None,
                    new_currency=None,
                )
                new_subscription = SubscriptionDto(
                    user_remna_id=subscription.user_remna_id,
                    status=SubscriptionStatus.ACTIVE,
                    traffic_limit=plan.traffic_limit,
                    device_limit=plan.device_limit,
                    traffic_limit_strategy=plan.traffic_limit_strategy,
                    tag=plan.tag,
                    internal_squads=plan.internal_squads,
                    external_squad=plan.external_squad,
                    expire_at=change.new_expire,
                    url="",
                    plan_snapshot=plan_snapshot,
                )
                remna_user = await self.remnawave.update_user(
                    user=target_user,
                    uuid=subscription.user_remna_id,
                    subscription=new_subscription,
                    reset_traffic=True,
                )
                new_subscription.status = SubscriptionStatus(remna_user.status)
                new_subscription.url = remna_user.subscription_url
                await self.subscription_dao.update_status(
                    subscription_id=subscription.id,
                    status=SubscriptionStatus.DELETED,
                )
            else:
                remna_user = await self.remnawave.create_user(user=target_user, plan=plan_snapshot)
                new_subscription = SubscriptionDto(
                    user_remna_id=remna_user.uuid,
                    status=SubscriptionStatus(remna_user.status),
                    traffic_limit=plan.traffic_limit,
                    device_limit=plan.device_limit,
                    traffic_limit_strategy=plan.traffic_limit_strategy,
                    tag=plan.tag,
                    internal_squads=plan.internal_squads,
                    external_squad=plan.external_squad,
                    expire_at=remna_user.expire_at,
                    url=remna_user.subscription_url,
                    plan_snapshot=plan_snapshot,
                )

            new_subscription = await self.subscription_dao.create(
                new_subscription,
                target_user.id,
            )

            await self.user_dao.set_trial_available(target_user.id, False)
            await self.uow.commit()

        logger.info(
            f"{actor.log} Set subscription with plan '{data.plan_id}' duration "
            f"'{data.duration}' for user '{data.user_id}'"
        )
