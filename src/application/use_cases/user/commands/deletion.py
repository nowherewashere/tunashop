from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from loguru import logger

from src.application.common import Interactor, SupportService
from src.application.common.dao import (
    LifecycleFollowupDao,
    OnboardingNudgeDao,
    RecentActivityDao,
    ReferralLedgerDao,
    SubscriptionDao,
    SupportDao,
    UserConnectionStateDao,
    UserDao,
)
from src.application.common.dao.auth import AuthSessionDao
from src.application.common.policy import Permission
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.core.exceptions import (
    UserDeletionPanelError,
    UserDeletionPrivilegedError,
    UserDeletionReferralLedgerError,
    UserDeletionSelfError,
    UserNotFoundError,
)


@dataclass(frozen=True)
class DeleteUserResult:
    telegram_id: Optional[int]
    remna_name: str
    deleted_panel_users: int


class DeleteUser(Interactor[int, DeleteUserResult]):
    """Erase an account so completely that the person comes back as a new customer.

    Built for verifying flows end to end: afterwards ``/start`` and the website both
    behave as they do for someone who has never touched the product — trial available,
    no subscription, no referral history, no onboarding state, no session.

    What has to happen, and why it is more than one ``DELETE``:

    - **The panel user goes first.** Its username is derived from the identity
      (``remnashop_<telegram_id>``), so a leftover panel user makes the *next* trial
      fail to create. If the panel refuses, nothing local is touched and the operator
      can retry — the opposite order would leave an unusable half-deleted account.
    - **The row, then everything hanging off it.** Subscriptions, transactions,
      referral edges and ledger, promocode activations, OAuth links, broadcast receipts
      and the support conversation are all FK ``ON DELETE CASCADE`` and go with it.
    - **Except the tables keyed by ``telegram_id``** — onboarding nudges, lifecycle
      followups, connection state. They carry no FK (fork-additive tables, kept off the
      shared ``User`` model on purpose), so nothing cascades and a brand-new user would
      be greeted with "уже подключался" and a chain of nudges. Deleted explicitly.
    - **And the state outside Postgres**: refresh tokens, the recent-activity board,
      the support forum topic and the in-bot support chat state.

    Deliberately left alone: ``events`` (append-only analytics keyed by the panel uuid —
    a re-registered user gets a new uuid, so their funnel starts clean anyway) and
    promocodes this user *owned* as an influencer (``owner_user_id`` is SET NULL: codes
    already handed out must not stop working because their owner was removed).
    """

    required_permission = Permission.USER_DELETE

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        support_dao: SupportDao,
        referral_ledger_dao: ReferralLedgerDao,
        onboarding_nudge_dao: OnboardingNudgeDao,
        lifecycle_followup_dao: LifecycleFollowupDao,
        connection_state_dao: UserConnectionStateDao,
        recent_activity_dao: RecentActivityDao,
        auth_session: AuthSessionDao,
        support_service: SupportService,
        remnawave: Remnawave,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.support_dao = support_dao
        self.referral_ledger_dao = referral_ledger_dao
        self.onboarding_nudge_dao = onboarding_nudge_dao
        self.lifecycle_followup_dao = lifecycle_followup_dao
        self.connection_state_dao = connection_state_dao
        self.recent_activity_dao = recent_activity_dao
        self.auth_session = auth_session
        self.support_service = support_service
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, user_id: int) -> DeleteUserResult:
        target = await self.user_dao.get_by_id(user_id)
        if target is None:
            raise UserNotFoundError(user_id)

        if target.id == actor.id:
            raise UserDeletionSelfError
        if target.is_privileged:
            raise UserDeletionPrivilegedError

        # Read before anything is destroyed: the one guard here that protects a *third
        # party* rather than the target.
        if await self.referral_ledger_dao.get_generated_kop(target.id):
            raise UserDeletionReferralLedgerError

        telegram_id = target.telegram_id
        # Every subscription the user ever had, not only the current one: each carries
        # its own panel user, and an old one left behind still holds a username.
        panel_ids: set[UUID] = {
            sub.user_remna_id for sub in await self.subscription_dao.get_all_by_user(target.id)
        }
        # Read while the row still exists — the conversation cascades away with it, and
        # its forum topic has to be closed from the outside afterwards.
        conversation = await self.support_dao.get_by_user(target.id)
        topic_id = conversation.telegram_topic_id if conversation else None

        deleted_panel_users = await self._delete_panel_users(target, panel_ids)

        async with self.uow:
            if telegram_id is not None:
                await self.onboarding_nudge_dao.delete_all(telegram_id)
                await self.lifecycle_followup_dao.delete_all(telegram_id)
                await self.connection_state_dao.delete(telegram_id)
            if not await self.user_dao.delete(target.id):
                raise UserNotFoundError(user_id)
            await self.uow.commit()

        # Outside the transaction and best-effort, exactly as the account merge does it:
        # the DB is the source of truth, and a Telegram/Redis hiccup must not turn a
        # committed delete into an error for the operator.
        await self._discard_external_state(target, topic_id)

        logger.warning(
            f"{actor.log} PERMANENTLY deleted user '{target.remna_name}' "
            f"(id={target.id}, telegram_id={telegram_id}, "
            f"panel users removed: {deleted_panel_users}/{len(panel_ids)})"
        )
        return DeleteUserResult(
            telegram_id=telegram_id,
            remna_name=target.remna_name,
            deleted_panel_users=deleted_panel_users,
        )

    async def _delete_panel_users(self, target: UserDto, panel_ids: set[UUID]) -> int:
        deleted = 0
        for remna_id in panel_ids:
            try:
                # False = already absent from the panel, which is the state we want.
                if await self.remnawave.delete_user(remna_id):
                    deleted += 1
            except Exception as e:
                logger.error(
                    f"Refusing to delete {target.log}: Remnawave user '{remna_id}' "
                    f"could not be removed: {e}"
                )
                raise UserDeletionPanelError from e
        return deleted

    async def _discard_external_state(self, target: UserDto, topic_id: Optional[int]) -> None:
        try:
            # Sessions live in Redis and now point at a row that is gone: a device still
            # signed in would otherwise only get 401s until its cookie expired.
            await self.auth_session.revoke_all_user_tokens(target.id)
        except Exception as e:
            logger.warning(f"Delete: failed to revoke sessions of user '{target.id}': {e}")

        try:
            await self.recent_activity_dao.forget(target.id)
        except Exception as e:
            logger.warning(f"Delete: failed to drop user '{target.id}' from activity: {e}")

        try:
            await self.support_service.discard_user(target.telegram_id, topic_id)
        except Exception as e:
            logger.warning(f"Delete: failed to discard support state of '{target.id}': {e}")
