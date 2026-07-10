from loguru import logger
from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import AccountMergeDao
from src.application.dto import PayoutDto
from src.core.constants import MERGE_SUPERSEDED_PAYOUT_REASON
from src.infrastructure.database.models import (
    BalanceSpend,
    BroadcastMessage,
    Payout,
    PromocodeActivation,
    Referral,
    ReferralCodeAlias,
    ReferralEvent,
    ReferralReward,
    Subscription,
    Transaction,
    User,
    UserOAuthProvider,
)
from src.infrastructure.database.models.referral_ledger import (
    PAYOUT_OPEN_STATUSES,
    PAYOUT_PROCESSING,
    PAYOUT_REJECTED,
)
from src.infrastructure.database.models.timestamp import NOW_FUNC

from .referral_ledger import to_payout_dto


class AccountMergeDaoImpl(AccountMergeDao):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reassign_children(self, survivor_id: int, loser_id: int) -> list[PayoutDto]:
        # Plain repoints — these user_id columns carry no per-user unique constraint.
        await self.session.execute(
            update(Subscription)
            .where(Subscription.user_id == loser_id)
            .values(user_id=survivor_id)
        )
        await self.session.execute(
            update(Transaction).where(Transaction.user_id == loser_id).values(user_id=survivor_id)
        )
        await self.session.execute(
            update(ReferralReward)
            .where(ReferralReward.user_id == loser_id)
            .values(user_id=survivor_id)
        )
        await self.session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.user_id == loser_id)
            .values(user_id=survivor_id)
        )
        # Money ledger (referral spec §2). These FKs cascade on user delete, so leaving
        # them out silently wipes the absorbed account's balance and payout history.
        await self.session.execute(
            update(Payout).where(Payout.user_id == loser_id).values(user_id=survivor_id)
        )
        await self.session.execute(
            update(BalanceSpend)
            .where(BalanceSpend.user_id == loser_id)
            .values(user_id=survivor_id)
        )

        await self._reassign_referrals(survivor_id, loser_id)
        await self._reassign_referral_events(survivor_id, loser_id)
        await self._reassign_promocode_activations(survivor_id, loser_id)
        await self._reassign_oauth_providers(survivor_id, loser_id)
        await self._reassign_referral_code(survivor_id, loser_id)
        # Runs last: it reconciles the survivor's payouts *after* the loser's have
        # been repointed onto it, which is the only moment two can be open at once.
        superseded = await self._collapse_open_payouts(survivor_id)

        logger.debug(f"Reassigned child records from user '{loser_id}' to '{survivor_id}'")
        return superseded

    async def _reassign_referral_code(self, survivor_id: int, loser_id: int) -> None:
        # The loser's `users.referral_code` dies with its row, so tombstone it onto the
        # survivor: links already shared with it keep attributing, and the freed 6-char
        # code is never re-issued (`get_by_referral_code` probes aliases too).
        # Aliases the loser had itself inherited from an earlier merge come along —
        # `referral_code_aliases.user_id` cascades, so leaving them behind deletes them.
        await self.session.execute(
            update(ReferralCodeAlias)
            .where(ReferralCodeAlias.user_id == loser_id)
            .values(user_id=survivor_id)
        )
        # The loser row still exists here (it is deleted only after every child is
        # repointed), so its live code is still readable.
        loser_code = await self.session.scalar(
            select(User.referral_code).where(User.id == loser_id)
        )
        if loser_code:
            await self.session.execute(
                insert(ReferralCodeAlias).values(code=loser_code, user_id=survivor_id)
            )

    async def _collapse_open_payouts(self, survivor_id: int) -> list[PayoutDto]:
        """Restore the single-open-payout invariant after both accounts' payouts merged.

        Keep exactly one open row and reject the rest; return the rejected ones so the
        caller can tell their owner once the merge has committed. Preference: a
        ``processing`` payout outranks a ``requested`` one (an operator is already
        settling it — closing it could double-pay), then the oldest, which has waited
        longest. ``id`` breaks the remaining tie, because ``created_at`` defaults to the
        transaction clock and two rows written in one transaction share it exactly.

        Rejecting destroys no money: ``balance = earned − spent − withdrawn(paid)`` and a
        rejected payout is none of those, so the survivor can immediately re-request the
        full combined balance.
        """
        open_ids = (
            await self.session.scalars(
                select(Payout.id)
                .where(
                    Payout.user_id == survivor_id,
                    Payout.status.in_(PAYOUT_OPEN_STATUSES),
                )
                .order_by(
                    (Payout.status == PAYOUT_PROCESSING).desc(),
                    Payout.created_at.asc(),
                    Payout.id.asc(),
                )
            )
        ).all()
        if len(open_ids) < 2:
            return []

        superseded_ids = open_ids[1:]
        rows = (
            await self.session.scalars(
                update(Payout)
                .where(Payout.id.in_(superseded_ids))
                .values(
                    status=PAYOUT_REJECTED,
                    reject_reason=MERGE_SUPERSEDED_PAYOUT_REASON,
                    processed_at=NOW_FUNC,
                )
                .returning(Payout)
            )
        ).all()
        logger.info(
            f"Merge: kept open payout '{open_ids[0]}' for user '{survivor_id}', "
            f"rejected superseded '{superseded_ids}'"
        )
        return [to_payout_dto(row) for row in rows]

    async def _reassign_referral_events(self, survivor_id: int, loser_id: int) -> None:
        # Commission rows earned *between* the two accounts must go: repointing them
        # would mint a self-referral (referrer == referred), i.e. commission farmed from
        # your own second account. Rows that are already self-referential are left
        # untouched — real code can never create them (attribution rejects self-referral).
        await self.session.execute(
            delete(ReferralEvent).where(
                ReferralEvent.referrer_id.in_((survivor_id, loser_id)),
                ReferralEvent.referred_id.in_((survivor_id, loser_id)),
                ReferralEvent.referrer_id != ReferralEvent.referred_id,
            )
        )
        # payment_id is globally unique, not per-user, so both columns repoint freely.
        await self.session.execute(
            update(ReferralEvent)
            .where(ReferralEvent.referrer_id == loser_id)
            .values(referrer_id=survivor_id)
        )
        await self.session.execute(
            update(ReferralEvent)
            .where(ReferralEvent.referred_id == loser_id)
            .values(referred_id=survivor_id)
        )

    async def _reassign_referrals(self, survivor_id: int, loser_id: int) -> None:
        # Drop any referral edge directly between the two accounts first, so a
        # repoint can never produce a self-referral (referrer_id == referred_id).
        await self.session.execute(
            delete(Referral).where(
                Referral.referrer_id.in_((survivor_id, loser_id)),
                Referral.referred_id.in_((survivor_id, loser_id)),
            )
        )
        # referrer_id is not unique — repoint every row the loser referred.
        await self.session.execute(
            update(Referral)
            .where(Referral.referrer_id == loser_id)
            .values(referrer_id=survivor_id)
        )
        # referred_id is unique (a user is invited at most once). Keep the
        # survivor's own "invited-by" edge if it exists; otherwise adopt the loser's.
        survivor_referred = await self.session.scalar(
            select(exists().where(Referral.referred_id == survivor_id))
        )
        if survivor_referred:
            await self.session.execute(delete(Referral).where(Referral.referred_id == loser_id))
        else:
            await self.session.execute(
                update(Referral)
                .where(Referral.referred_id == loser_id)
                .values(referred_id=survivor_id)
            )

    async def _reassign_promocode_activations(self, survivor_id: int, loser_id: int) -> None:
        # (promocode_id, user_id) is unique — drop the loser's activations for
        # promocodes the survivor already redeemed, then repoint the rest.
        already = select(PromocodeActivation.promocode_id).where(
            PromocodeActivation.user_id == survivor_id
        )
        await self.session.execute(
            delete(PromocodeActivation).where(
                PromocodeActivation.user_id == loser_id,
                PromocodeActivation.promocode_id.in_(already),
            )
        )
        await self.session.execute(
            update(PromocodeActivation)
            .where(PromocodeActivation.user_id == loser_id)
            .values(user_id=survivor_id)
        )

    async def _reassign_oauth_providers(self, survivor_id: int, loser_id: int) -> None:
        # (user_id, provider) is unique — drop the loser's providers the survivor
        # already has linked, then repoint the rest.
        already = select(UserOAuthProvider.provider).where(
            UserOAuthProvider.user_id == survivor_id
        )
        await self.session.execute(
            delete(UserOAuthProvider).where(
                UserOAuthProvider.user_id == loser_id,
                UserOAuthProvider.provider.in_(already),
            )
        )
        await self.session.execute(
            update(UserOAuthProvider)
            .where(UserOAuthProvider.user_id == loser_id)
            .values(user_id=survivor_id)
        )
