from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from adaptix import Retort
from loguru import logger

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import PromocodeDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, PromocodeDto, SubscriptionDto, UserDto
from src.application.dto.promocode import PromocodeActivationDto
from src.application.events.system import PromocodeActivatedEvent
from src.application.services import SubscriptionProrationService
from src.application.use_cases.promocode.queries.validate import (
    ValidatePromocode,
    ValidatePromocodeDto,
)
from src.application.use_cases.referral.commands.attachment import (
    AttachReferral,
    AttachReferralDto,
)
from src.core.enums import PromocodeRewardType, SubscriptionStatus
from src.core.utils.converters import days_to_datetime
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class ActivatePromocodeDto:
    code: str
    user: UserDto


@dataclass(frozen=True)
class _PendingReward:
    subscription_update: Optional[SubscriptionDto] = None
    subscription_create: Optional[SubscriptionDto] = None
    user_update: Optional[UserDto] = None


class ActivatePromocode(Interactor[ActivatePromocodeDto, PromocodeDto]):
    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        promocode_dao: PromocodeDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        validate_promocode: ValidatePromocode,
        attach_referral: AttachReferral,
        event_publisher: EventPublisher,
        retort: Retort,
        proration: SubscriptionProrationService,
    ) -> None:
        self.uow = uow
        self.promocode_dao = promocode_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.validate_promocode = validate_promocode
        self.attach_referral = attach_referral
        self.event_publisher = event_publisher
        self.retort = retort
        self.proration = proration

    async def _execute(self, actor: UserDto, data: ActivatePromocodeDto) -> PromocodeDto:
        user = data.user

        promo = await self.validate_promocode(
            actor, ValidatePromocodeDto(code=data.code, user=user)
        )

        subscription = await self.subscription_dao.get_current(user.id)

        # Remnawave calls happen OUTSIDE the transaction: if any raises, the
        # exception propagates and nothing is persisted (promocode not consumed).
        pending = await self._apply_reward_remote(actor, user, promo, subscription)

        async with self.uow:
            assert promo.id is not None
            activation = PromocodeActivationDto(
                promocode_id=promo.id,
                user_id=user.id,
                activated_at=datetime_now(),
            )
            await self.promocode_dao.create_activation(
                activation,
                max_activations=promo.max_activations,
                is_reusable=promo.is_reusable,
            )

            await self._persist_reward(user, pending)
            await self.uow.commit()

        logger.info(f"{actor.log} Activated promocode '{promo.code}'")

        # Influencer attribution runs only after the activation has committed (reward granted),
        # so a code whose reward could not apply never attaches a referrer.
        await self._attach_owner_referral(user, promo)

        event = PromocodeActivatedEvent(
            user_id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            name=user.name,
            promocode_code=promo.code,
            reward_type=promo.reward_type.value,
            reward=promo.reward,
            plan_name=(str(promo.plan_snapshot.get("name")), {})
            if promo.plan_snapshot and promo.plan_snapshot.get("name")
            else "",
        )
        await self.event_publisher.publish(event)

        return promo

    async def _attach_owner_referral(self, user: UserDto, promo: PromocodeDto) -> None:
        """Attach the redeeming user to the promocode owner's (influencer's) referral.

        AttachReferral is the single authority on attribution: it already skips when the
        referral system is off, on self-referral, and — crucially — when the user ALREADY
        has a referrer (a promocode must never overwrite an existing inviter). No guard is
        duplicated here. Best-effort: a failure must not undo the reward just granted.
        """
        if promo.owner_user_id is None:
            return
        owner = await self.user_dao.get_by_id(promo.owner_user_id)
        if not owner or not owner.referral_code:
            logger.warning(
                f"Promocode '{promo.code}' owner id={promo.owner_user_id} is missing or has "
                f"no referral code; skipping influencer attribution"
            )
            return
        try:
            await self.attach_referral.system(
                AttachReferralDto(user_id=user.id, referral_code=owner.referral_code)
            )
        except Exception as exc:
            logger.error(
                f"Failed to attach influencer referral for promocode '{promo.code}' "
                f"(owner id={promo.owner_user_id}, user id={user.id}): {exc}"
            )

    async def _apply_reward_remote(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        match promo.reward_type:
            case PromocodeRewardType.DURATION:
                return await self._apply_duration(actor, user, promo, subscription)
            case PromocodeRewardType.TRAFFIC:
                return await self._apply_traffic(actor, user, promo, subscription)
            case PromocodeRewardType.DEVICES:
                return await self._apply_devices(actor, user, promo, subscription)
            case PromocodeRewardType.SUBSCRIPTION:
                return await self._apply_subscription(actor, user, promo, subscription)
            case PromocodeRewardType.PERSONAL_DISCOUNT:
                return self._apply_personal_discount(actor, user, promo)
            case PromocodeRewardType.PURCHASE_DISCOUNT:
                return self._apply_purchase_discount(actor, user, promo)

    async def _persist_reward(self, user: UserDto, pending: _PendingReward) -> None:
        if pending.subscription_update is not None:
            await self.subscription_dao.update(pending.subscription_update)
        if pending.subscription_create is not None:
            try:
                await self.subscription_dao.create(
                    subscription=pending.subscription_create, user_id=user.id
                )
            except Exception:
                # Remote user was already created in the remote phase; a failure
                # here leaves a remote orphan (inherent dual-write without 2PC).
                logger.error(
                    f"Failed to persist new subscription after Remnawave create_user "
                    f"(remote uuid={pending.subscription_create.user_remna_id}); "
                    f"possible remote orphan"
                )
                raise
        if pending.user_update is not None:
            await self.user_dao.update(pending.user_update)

    async def _apply_duration(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not subscription or promo.reward is None:
            return _PendingReward()
        if promo.reward == 0:
            # 0 days means a permanent (unlimited) subscription.
            subscription.expire_at = days_to_datetime(0)
            log_detail = "unlimited"
        else:
            subscription.expire_at = subscription.expire_at + timedelta(days=promo.reward)
            log_detail = f"+{promo.reward} days"
        await self.remnawave.update_user(
            user=user,
            uuid=subscription.user_remna_id,
            subscription=subscription,
        )
        logger.info(f"{actor.log} DURATION reward: {log_detail} applied")
        return _PendingReward(subscription_update=subscription)

    async def _apply_traffic(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not subscription or promo.reward is None:
            return _PendingReward()
        if promo.reward == 0:
            # 0 GB means an unlimited traffic limit.
            subscription.traffic_limit = 0
            log_detail = "unlimited"
        else:
            subscription.traffic_limit = subscription.traffic_limit + promo.reward
            log_detail = f"+{promo.reward} GB"
        await self.remnawave.update_user(
            user=user,
            uuid=subscription.user_remna_id,
            subscription=subscription,
        )
        logger.info(f"{actor.log} TRAFFIC reward: {log_detail} applied")
        return _PendingReward(subscription_update=subscription)

    async def _apply_devices(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not subscription or promo.reward is None:
            return _PendingReward()
        if promo.reward == 0:
            # 0 devices means an unlimited device limit.
            subscription.device_limit = 0
            log_detail = "unlimited"
        else:
            subscription.device_limit = subscription.device_limit + promo.reward
            log_detail = f"+{promo.reward} devices"
        await self.remnawave.update_user(
            user=user,
            uuid=subscription.user_remna_id,
            subscription=subscription,
        )
        logger.info(f"{actor.log} DEVICES reward: {log_detail} applied")
        return _PendingReward(subscription_update=subscription)

    async def _apply_subscription(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
        subscription: Optional[SubscriptionDto],
    ) -> _PendingReward:
        if not promo.plan_snapshot:
            return _PendingReward()
        plan = self.retort.load(promo.plan_snapshot, PlanSnapshotDto)
        if subscription:
            # A promo reward carries no payment, so there is no monetary basis for
            # value-proration: preserve the user's remaining days on top of the new
            # plan's duration instead of wiping them. Computed BEFORE the snapshot is
            # overwritten so it reads the current (old) plan's remaining time.
            change = self.proration.compute_change_expiry(
                current=subscription,
                new_duration=plan.duration,
                new_price=None,
                new_currency=None,
            )
            # Keep the local subscription in sync with the new plan pushed to the
            # panel; otherwise the DB keeps stale limits/expiry and later updates
            # would overwrite the panel with outdated values. Push the computed expiry
            # via subscription=... (plan=... would reset it to now + new duration).
            subscription.traffic_limit = plan.traffic_limit
            subscription.device_limit = plan.device_limit
            subscription.traffic_limit_strategy = plan.traffic_limit_strategy
            subscription.tag = plan.tag
            subscription.internal_squads = plan.internal_squads
            subscription.external_squad = plan.external_squad
            subscription.expire_at = change.new_expire
            subscription.plan_snapshot = plan
            updated = await self.remnawave.update_user(
                user=user,
                uuid=subscription.user_remna_id,
                subscription=subscription,
                reset_traffic=True,
            )
            subscription.status = SubscriptionStatus(updated.status)
            subscription.url = updated.subscription_url
            logger.info(
                f"{actor.log} SUBSCRIPTION reward applied "
                f"(basis={change.basis}, bonus_days={change.bonus_days})"
            )
            return _PendingReward(subscription_update=subscription)
        created = await self.remnawave.create_user(user=user, plan=plan)
        new_sub = SubscriptionDto(
            user_remna_id=created.uuid,
            status=SubscriptionStatus(created.status),
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=created.expire_at,
            url=created.subscription_url,
            plan_snapshot=plan,
        )
        logger.info(f"{actor.log} SUBSCRIPTION reward applied")
        return _PendingReward(subscription_create=new_sub)

    def _apply_personal_discount(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
    ) -> _PendingReward:
        if not promo.reward:
            return _PendingReward()
        user.personal_discount = promo.reward
        logger.info(f"{actor.log} PERSONAL_DISCOUNT reward: {promo.reward}% applied")
        return _PendingReward(user_update=user)

    def _apply_purchase_discount(
        self,
        actor: UserDto,
        user: UserDto,
        promo: PromocodeDto,
    ) -> _PendingReward:
        if not promo.reward:
            return _PendingReward()
        user.purchase_discount = promo.reward
        logger.info(f"{actor.log} PURCHASE_DISCOUNT reward: {promo.reward}% applied")
        return _PendingReward(user_update=user)
