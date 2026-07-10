from typing import Callable
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger

from src.application.common import EventPublisher
from src.application.common.dao import AccountMergeDao, SubscriptionDao, UserDao
from src.application.common.dao.auth import AuthSessionDao
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import PayoutDto, SubscriptionDto, UserDto
from src.application.events import PayoutRejectedEvent
from src.application.use_cases.referral.queries.summary import (
    GetReferralSummary,
    GetReferralSummaryDto,
)
from src.core.constants import MERGE_SUPERSEDED_PAYOUT_REASON
from src.core.enums import SubscriptionStatus
from src.core.utils.money import kop_to_rub

# Stamps the absorbed account's identity onto the survivor. Called *after* the loser
# row is deleted, which is the only point at which a unique identity column
# (`ix_users_email`, `ix_users_telegram_id`) is free to move across rows.
StampIdentity = Callable[[UserDto, UserDto], None]


class AccountMergeService:
    """Absorb one `users` row into another, in a single transaction.

    Both directions of the symmetric merge run through here:

    - **Telegram side** (`LinkTelegram`) — signed in with email, attaching a Telegram
      that already has its own bot account.
    - **Email side** (`ConfirmEmailVerification`) — signed in with Telegram, confirming
      an email that already belongs to a separate site account.

    The survivor is always the account the user is *acting from*: they are signed into
    it, it is the profile the cabinet is showing them, and its referral code is the one
    they have been sharing. The absorbed row's identity moves onto it; the row itself
    is deleted.

    The caller supplies only `stamp_identity`, which moves the identity columns that
    differ per direction. Everything that must happen on *any* merge — the guards, the
    child repointing, the ordering, the subscription and Remnawave reconciliation —
    lives here, so neither direction can quietly skip a step.

    Two outcomes are refused rather than guessed at, because both would silently
    destroy something live:

    - both accounts hold an active paid subscription (`two_active_subscriptions`);
    - the absorbed account is blocked (`account_blocked`).
    """

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        account_merge: AccountMergeDao,
        remnawave: Remnawave,
        auth_session: AuthSessionDao,
        event_publisher: EventPublisher,
        get_referral_summary: GetReferralSummary,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.account_merge = account_merge
        self.remnawave = remnawave
        self.auth_session = auth_session
        self.event_publisher = event_publisher
        self.get_referral_summary = get_referral_summary

    async def merge(
        self,
        survivor: UserDto,
        loser: UserDto,
        stamp_identity: StampIdentity,
    ) -> UserDto:
        if loser.is_blocked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_blocked")

        survivor_sub = await self.subscription_dao.get_current(survivor.id)
        loser_sub = await self.subscription_dao.get_current(loser.id)
        if self._is_active_paid(survivor_sub) and self._is_active_paid(loser_sub):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="two_active_subscriptions",
            )

        async with self.uow:
            superseded_payouts = await self.account_merge.reassign_children(survivor.id, loser.id)

            # Delete the absorbed row BEFORE stamping its identity onto the survivor.
            # `ix_users_email` and `ix_users_telegram_id` are unique indexes, so the two
            # rows cannot both carry that identity — not even mid-transaction — and
            # updating the survivor first raises a UniqueViolationError. The loser's
            # children were just repointed onto the survivor, so this cascades nothing.
            await self.user_dao.delete(loser.id)

            stamp_identity(survivor, loser)
            self._merge_scalars(survivor, loser)

            best_sub = self._pick_current(survivor_sub, loser_sub)

            updated = await self.user_dao.update(survivor)
            if not updated:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found during account merge",
                )

            # Point the survivor at the winning subscription. `current_subscription_id`
            # is not a UserDto field, so it's set through its dedicated DAO method
            # rather than as a phantom attribute on the DTO.
            if best_sub is not None:
                await self.user_dao.set_current_subscription_by_id(survivor.id, best_sub.id)

            # The survivor now owns every subscription of both accounts, but only the
            # winning one stays live. Soft-delete the rest in the DB now (inside the
            # transaction); their Remnawave panel users are removed after commit.
            orphan_remna_ids = await self._retire_losing_subscriptions(survivor.id, best_sub)

            await self.uow.commit()

        # The absorbed row is gone, but its refresh tokens live in Redis, outside the
        # transaction. They now point at a deleted user id, so they can only ever produce
        # 401s — revoke them so a device still signed into that account (an email account
        # is often open on a laptop) is sent back to the login screen, where signing in
        # again lands on the survivor. After commit, never before: a rolled-back merge
        # must not log anyone out.
        try:
            await self.auth_session.revoke_all_user_tokens(loser.id)
        except Exception as e:
            logger.warning(f"Merge: failed to revoke refresh tokens of user {loser.id}: {e}")

        # Panel reconciliation is best-effort and OUTSIDE the transaction: the DB is
        # the source of truth, so a panel hiccup only leaves stale metadata / a logged
        # orphan to reconcile — never a half-applied merge that could delete a live config.
        if best_sub is not None:
            # The kept panel user may have been created under the absorbed account and so
            # carries its identity. Push the survivor's onto it; passing the same
            # subscription re-writes its plan fields to their current values (no change).
            # Only `telegram_id`/`email`/`description` move — the panel username is left
            # alone on purpose, since it is baked into the live subscription URL.
            try:
                await self.remnawave.update_user(
                    updated, best_sub.user_remna_id, subscription=best_sub
                )
            except Exception as e:
                logger.warning(
                    f"Merge: failed to sync identity onto Remnawave user "
                    f"{best_sub.user_remna_id}: {e}"
                )

        for remna_id in orphan_remna_ids:
            try:
                await self.remnawave.delete_user(remna_id)
            except Exception as e:
                logger.warning(f"Merge: failed to delete orphan Remnawave user {remna_id}: {e}")

        await self._notify_superseded_payouts(updated, superseded_payouts)

        logger.info(f"Merged user '{loser.id}' into '{survivor.id}'")
        return updated

    async def _notify_superseded_payouts(
        self, survivor: UserDto, payouts: list[PayoutDto]
    ) -> None:
        """Tell the survivor about each payout the merge had to close.

        Closing a withdrawal request without a word is the kind of silence that reads as
        lost money, even though the balance is untouched — so say it, exactly as
        ``RejectPayout`` does when an operator rejects one by hand.

        Post-commit and best-effort: the merge has already landed, and a failure to build
        the summary or reach the bus must not turn a committed merge into a 500 for the
        caller. Web-only survivors are dropped downstream by the notifier.
        """
        if not payouts:
            return

        try:
            # The one source of truth for the balance formula; read *after* commit so it
            # reflects the merged ledger the user will actually see.
            summary = await self.get_referral_summary.system(GetReferralSummaryDto(survivor.id))
            balance = kop_to_rub(summary.balance_kop)
            for payout in payouts:
                await self.event_publisher.publish(
                    PayoutRejectedEvent(
                        user=survivor,
                        amount=kop_to_rub(payout.amount_kop),
                        reason=MERGE_SUPERSEDED_PAYOUT_REASON,
                        balance=balance,
                    )
                )
        except Exception as e:
            logger.warning(
                f"Merge: failed to notify user {survivor.id} about "
                f"{len(payouts)} superseded payout(s): {e}"
            )

    @staticmethod
    def _merge_scalars(survivor: UserDto, loser: UserDto) -> None:
        """Fold the absorbed account's non-identity state into the survivor.

        Each rule keeps whatever the user already earned: points add up, a discount
        never shrinks, and an accepted-rules flag never un-accepts. `is_trial_available`
        is the one AND — a trial spent on either account is spent.
        """
        survivor.points += loser.points
        survivor.is_rules_accepted = survivor.is_rules_accepted or loser.is_rules_accepted
        survivor.is_trial_available = survivor.is_trial_available and loser.is_trial_available
        survivor.personal_discount = max(survivor.personal_discount, loser.personal_discount)
        survivor.purchase_discount = max(survivor.purchase_discount, loser.purchase_discount)

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
        survivor_sub: "SubscriptionDto | None",
        loser_sub: "SubscriptionDto | None",
    ) -> "SubscriptionDto | None":
        # Prefer a still-valid sub over an expired one, a paid sub over a trial,
        # then the later expiry — so the merged account surfaces its best config.
        candidates = [s for s in (survivor_sub, loser_sub) if s is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda s: (not s.is_expired, not s.is_trial, s.expire_at))
