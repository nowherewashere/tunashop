import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.exc import IntegrityError

from src.application.common import Interactor
from src.application.common.dao import AccountMergeDao, SubscriptionDao, UserDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import SubscriptionDto, UserDto
from src.application.use_cases.auth._telegram import (
    parse_webapp_init_data,
    verify_telegram_auth,
    verify_telegram_webapp_init_data,
)
from src.application.use_cases.user.commands.web_registration import (
    RegisterWebUser,
    RegisterWebUserDto,
)
from src.core.config import AppConfig
from src.core.enums import AuthType, SubscriptionStatus


@dataclass
class TelegramAuthData:
    id: int
    first_name: str
    last_name: "str | None"
    username: "str | None"
    payload: dict[str, Any]


async def _get_or_create_telegram_user(
    user_dao: UserDao,
    register_web_user: RegisterWebUser,
    config: AppConfig,
    data: TelegramAuthData,
) -> UserDto:
    user = await user_dao.get_by_telegram_id(data.id)
    if user:
        if user.is_blocked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")
        return user

    name_parts = [data.first_name]
    if data.last_name:
        name_parts.append(data.last_name)

    new_user = UserDto(
        telegram_id=data.id,
        auth_type=AuthType.TELEGRAM,
        username=data.username,
        name=" ".join(name_parts),
        language=config.default_locale,
    )

    try:
        return await register_web_user.system(RegisterWebUserDto(user=new_user))
    except IntegrityError as e:
        existing = await user_dao.get_by_telegram_id(data.id)
        if existing:
            return existing
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="User creation conflict"
        ) from e


class AuthenticateTelegram(Interactor[TelegramAuthData, UserDto]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        user_dao: UserDao,
        register_web_user: RegisterWebUser,
    ) -> None:
        self.config = config
        self.user_dao = user_dao
        self.register_web_user = register_web_user

    async def _execute(self, actor: UserDto, data: TelegramAuthData) -> UserDto:
        bot_token = self.config.bot.token.get_secret_value()
        if not verify_telegram_auth(data.payload, bot_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Telegram auth data",
            )
        return await _get_or_create_telegram_user(
            self.user_dao, self.register_web_user, self.config, data
        )


class AuthenticateTelegramWebApp(Interactor[str, UserDto]):
    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        user_dao: UserDao,
        register_web_user: RegisterWebUser,
    ) -> None:
        self.config = config
        self.user_dao = user_dao
        self.register_web_user = register_web_user

    async def _execute(self, actor: UserDto, data: str) -> UserDto:
        bot_token = self.config.bot.token.get_secret_value()
        if not verify_telegram_webapp_init_data(data, bot_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Telegram WebApp init data",
            )

        fields = parse_webapp_init_data(data)
        raw_user = fields.get("user")
        if not raw_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing user in init data",
            )
        user_payload = json.loads(raw_user)

        auth_data = TelegramAuthData(
            id=int(user_payload["id"]),
            first_name=str(user_payload.get("first_name", "")),
            last_name=user_payload.get("last_name"),
            username=user_payload.get("username"),
            payload=user_payload,
        )
        return await _get_or_create_telegram_user(
            self.user_dao, self.register_web_user, self.config, auth_data
        )


@dataclass
class LinkTelegramData:
    id: int
    username: "str | None"
    payload: dict[str, Any]


class LinkTelegram(Interactor[LinkTelegramData, UserDto]):
    """Attach a Telegram identity to the authenticated (site) account.

    Three outcomes, all keyed off whether that Telegram already owns a row:

    - No existing row  → plain link: stamp ``telegram_id`` onto the actor.
    - A separate bot account owns it → **merge** it into the actor: repoint its
      subscription/referrals/history, sum referral points, adopt its Telegram
      identity, then delete the emptied row. The bot's Remnawave panel user is
      preserved (we repoint, never recreate), so the existing VPN config keeps
      working — and because the actor now carries that ``telegram_id``, its
      ``remna_name`` matches the panel user too.
    - Both accounts already have an active paid subscription → refuse with
      ``two_active_subscriptions``; combining two live VPN configs is a support
      decision, not something we silently destroy.
    """

    required_permission = Permission.PUBLIC

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        account_merge: AccountMergeDao,
        remnawave: Remnawave,
    ) -> None:
        self.config = config
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.account_merge = account_merge
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: LinkTelegramData) -> UserDto:
        bot_token = self.config.bot.token.get_secret_value()
        if not verify_telegram_auth(data.payload, bot_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Telegram auth data",
            )

        if actor.telegram_id == data.id:
            return actor

        if actor.telegram_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="already_linked_other",
            )

        existing = await self.user_dao.get_by_telegram_id(data.id)
        if existing is None:
            return await self._link(actor, data)
        if existing.id == actor.id:
            return actor
        return await self._merge(actor, existing, data)

    async def _link(self, actor: UserDto, data: LinkTelegramData) -> UserDto:
        actor.telegram_id = data.id
        if data.username is not None:
            actor.username = data.username

        async with self.uow:
            updated = await self.user_dao.update(actor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during Telegram link",
                )
            await self.uow.commit()
        return updated

    async def _merge(self, actor: UserDto, loser: UserDto, data: LinkTelegramData) -> UserDto:
        if loser.is_blocked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_blocked")

        actor_sub = await self.subscription_dao.get_current(actor.id)
        loser_sub = await self.subscription_dao.get_current(loser.id)
        if self._is_active_paid(actor_sub) and self._is_active_paid(loser_sub):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="two_active_subscriptions",
            )

        async with self.uow:
            await self.account_merge.reassign_children(actor.id, loser.id)

            # Delete the absorbed row BEFORE stamping its telegram_id onto the
            # survivor. ``ix_users_telegram_id`` is a unique index, so the two rows
            # cannot both carry that telegram_id — not even mid-transaction — and
            # updating the survivor first raises a UniqueViolationError. The loser's
            # children were just repointed onto the survivor, so this cascades nothing.
            await self.user_dao.delete(loser.id)

            actor.telegram_id = data.id
            if actor.username is None:
                actor.username = data.username or loser.username
            actor.points += loser.points
            actor.is_rules_accepted = actor.is_rules_accepted or loser.is_rules_accepted
            actor.is_trial_available = actor.is_trial_available and loser.is_trial_available
            actor.personal_discount = max(actor.personal_discount, loser.personal_discount)
            actor.purchase_discount = max(actor.purchase_discount, loser.purchase_discount)

            best_sub = self._pick_current(actor_sub, loser_sub)
            if best_sub is not None:
                actor.current_subscription_id = best_sub.id

            updated = await self.user_dao.update(actor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during Telegram link",
                )

            # The survivor now owns every subscription of both accounts, but only the
            # winning one stays live. Soft-delete the rest in the DB now (inside the
            # transaction); their Remnawave panel users are removed after commit.
            orphan_remna_ids = await self._retire_losing_subscriptions(actor.id, best_sub)

            await self.uow.commit()

        # Panel cleanup is best-effort and OUTSIDE the transaction: the DB already
        # treats these subs as deleted, so a panel hiccup only leaves a logged orphan
        # to reconcile — never a half-applied merge that could delete a live config.
        for remna_id in orphan_remna_ids:
            try:
                await self.remnawave.delete_user(remna_id)
            except Exception as e:
                logger.warning(f"Merge: failed to delete orphan Remnawave user {remna_id}: {e}")

        return updated

    async def _retire_losing_subscriptions(
        self, survivor_id: int, best_sub: "SubscriptionDto | None"
    ) -> set[UUID]:
        """Mark every non-winning subscription DELETED; return the distinct Remnawave
        user ids to remove (all except the winner's, so the panel keeps exactly one)."""
        if best_sub is None:
            return set()

        keep = best_sub.user_remna_id
        orphans: set[UUID] = set()
        for sub in await self.subscription_dao.get_all_by_user(survivor_id):
            if sub.user_remna_id == keep:
                continue
            orphans.add(sub.user_remna_id)
            if sub.status != SubscriptionStatus.DELETED:
                await self.subscription_dao.update_status(sub.id, SubscriptionStatus.DELETED)
        return orphans

    @staticmethod
    def _is_active_paid(sub: "SubscriptionDto | None") -> bool:
        return sub is not None and not sub.is_expired and not sub.is_trial

    @staticmethod
    def _pick_current(
        actor_sub: "SubscriptionDto | None",
        loser_sub: "SubscriptionDto | None",
    ) -> "SubscriptionDto | None":
        # Prefer a still-valid sub over an expired one, a paid sub over a trial,
        # then the later expiry — so the merged account surfaces its best config.
        candidates = [s for s in (actor_sub, loser_sub) if s is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda s: (not s.is_expired, not s.is_trial, s.expire_at))
