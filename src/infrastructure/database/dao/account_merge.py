from loguru import logger
from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import AccountMergeDao
from src.infrastructure.database.models import (
    BalanceSpend,
    BroadcastMessage,
    Payout,
    PromocodeActivation,
    Referral,
    ReferralEvent,
    ReferralReward,
    Subscription,
    Transaction,
    UserOAuthProvider,
)


class AccountMergeDaoImpl(AccountMergeDao):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reassign_children(self, survivor_id: int, loser_id: int) -> None:
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

        logger.debug(f"Reassigned child records from user '{loser_id}' to '{survivor_id}'")

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
