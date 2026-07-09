from typing import Optional

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.application.common.dao import ReferralLedgerDao
from src.application.dto import BalanceSpendDto, PayoutDto, ReferralEventDto
from src.infrastructure.database.models.referral_ledger import (
    PAYOUT_METHOD_CRYPTO,
    PAYOUT_OPEN_STATUSES,
    PAYOUT_PAID,
    PAYOUT_PROCESSING,
    PAYOUT_REJECTED,
    PAYOUT_REQUESTED,
    BalanceSpend,
    Payout,
    ReferralEvent,
)
from src.infrastructure.database.models.timestamp import NOW_FUNC

from .base import BaseDaoImpl


class ReferralLedgerDaoImpl(BaseDaoImpl, ReferralLedgerDao):
    # --- earning side (referral_events) ---
    async def add_commission(self, event: ReferralEventDto) -> bool:
        stmt = (
            insert(ReferralEvent)
            .values(
                referrer_id=event.referrer_id,
                referred_id=event.referred_id,
                payment_id=event.payment_id,
                payment_kop=event.payment_kop,
                commission_kop=event.commission_kop,
                rate_bp=event.rate_bp,
                kind=event.kind,
            )
            .on_conflict_do_nothing(index_elements=["payment_id"])
            .returning(ReferralEvent.id)
        )
        inserted = await self.session.scalar(stmt) is not None
        if inserted:
            logger.debug(
                f"Referral commission '{event.commission_kop}' kop recorded: "
                f"referrer id='{event.referrer_id}' payment '{event.payment_id}'"
            )
        else:
            logger.debug(f"Referral commission for payment '{event.payment_id}' already recorded")
        return inserted

    async def get_earned_kop(self, referrer_id: int) -> int:
        stmt = select(func.coalesce(func.sum(ReferralEvent.commission_kop), 0)).where(
            ReferralEvent.referrer_id == referrer_id
        )
        return int(await self.session.scalar(stmt) or 0)

    async def get_paying_count(self, referrer_id: int) -> int:
        stmt = select(func.count(func.distinct(ReferralEvent.referred_id))).where(
            ReferralEvent.referrer_id == referrer_id
        )
        return int(await self.session.scalar(stmt) or 0)

    # --- spend side (balance_spends) ---
    async def add_balance_spend(self, spend: BalanceSpendDto) -> BalanceSpendDto:
        db_spend = BalanceSpend(
            user_id=spend.user_id,
            amount_kop=spend.amount_kop,
            applied_term=spend.applied_term,
            remnawave_ref=spend.remnawave_ref,
        )
        self.session.add(db_spend)
        await self.session.flush()
        logger.debug(
            f"Balance spend '{spend.amount_kop}' kop recorded for user id='{spend.user_id}'"
        )
        spend.id = db_spend.id
        return spend

    async def get_spent_kop(self, user_id: int) -> int:
        stmt = select(func.coalesce(func.sum(BalanceSpend.amount_kop), 0)).where(
            BalanceSpend.user_id == user_id
        )
        return int(await self.session.scalar(stmt) or 0)

    # --- withdrawal side (payouts) ---
    async def get_withdrawn_kop(self, user_id: int) -> int:
        stmt = select(func.coalesce(func.sum(Payout.amount_kop), 0)).where(
            Payout.user_id == user_id,
            Payout.status == PAYOUT_PAID,
        )
        return int(await self.session.scalar(stmt) or 0)

    async def get_open_payout(self, user_id: int) -> Optional[PayoutDto]:
        stmt = (
            select(Payout)
            .where(
                Payout.user_id == user_id,
                Payout.status.in_(PAYOUT_OPEN_STATUSES),
            )
            .order_by(Payout.created_at.desc())
            .limit(1)
        )
        row = await self.session.scalar(stmt)
        return self._to_payout_dto(row) if row else None

    async def create_payout(self, payout: PayoutDto) -> PayoutDto:
        db_payout = Payout(
            user_id=payout.user_id,
            method=payout.method,
            amount_kop=payout.amount_kop,
            status=payout.status,
            crypto_wallet=payout.crypto_wallet,
            crypto_asset=payout.crypto_asset,
            crypto_network=payout.crypto_network,
        )
        self.session.add(db_payout)
        await self.session.flush()
        logger.debug(
            f"Payout '{payout.amount_kop}' kop ({payout.method}) requested for "
            f"user id='{payout.user_id}'"
        )
        return self._to_payout_dto(db_payout)

    async def get_payout(self, payout_id: int) -> Optional[PayoutDto]:
        row = await self.session.get(Payout, payout_id)
        return self._to_payout_dto(row) if row else None

    async def list_payouts_by_status(
        self, status: str, limit: int = 50, offset: int = 0
    ) -> list[PayoutDto]:
        stmt = (
            select(Payout)
            .where(Payout.status == status)
            .order_by(Payout.created_at)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(stmt)
        return [self._to_payout_dto(row) for row in result.all()]

    async def count_payouts_by_status(self, status: str) -> int:
        stmt = select(func.count()).select_from(Payout).where(Payout.status == status)
        return int(await self.session.scalar(stmt) or 0)

    async def get_last_crypto_wallet(self, user_id: int) -> Optional[PayoutDto]:
        stmt = (
            select(Payout)
            .where(
                Payout.user_id == user_id,
                Payout.method == PAYOUT_METHOD_CRYPTO,
                Payout.crypto_wallet.is_not(None),
            )
            .order_by(Payout.created_at.desc())
            .limit(1)
        )
        row = await self.session.scalar(stmt)
        return self._to_payout_dto(row) if row else None

    # --- operator transitions ---
    async def mark_processing(self, payout_id: int, operator_id: Optional[int]) -> None:
        await self.session.execute(
            update(Payout)
            .where(Payout.id == payout_id)
            .values(status=PAYOUT_PROCESSING, operator_id=operator_id, processed_at=NOW_FUNC)
        )
        logger.debug(f"Payout '{payout_id}' -> processing")

    async def mark_paid(self, payout_id: int, operator_id: int, tx_hash: Optional[str]) -> None:
        await self.session.execute(
            update(Payout)
            .where(Payout.id == payout_id)
            .values(
                status=PAYOUT_PAID,
                operator_id=operator_id,
                tx_hash=tx_hash,
                processed_at=NOW_FUNC,
            )
        )
        logger.debug(f"Payout '{payout_id}' -> paid")

    async def mark_rejected(self, payout_id: int, operator_id: int, reason: str) -> None:
        await self.session.execute(
            update(Payout)
            .where(Payout.id == payout_id)
            .values(
                status=PAYOUT_REJECTED,
                operator_id=operator_id,
                reject_reason=reason,
                processed_at=NOW_FUNC,
            )
        )
        logger.debug(f"Payout '{payout_id}' -> rejected")

    async def collect_crypto_batch(self, batch_id: str) -> list[PayoutDto]:
        await self.session.execute(
            update(Payout)
            .where(
                Payout.status == PAYOUT_REQUESTED,
                Payout.method == PAYOUT_METHOD_CRYPTO,
            )
            .values(status=PAYOUT_PROCESSING, batch_id=batch_id, processed_at=NOW_FUNC)
        )
        result = await self.session.scalars(
            select(Payout).where(Payout.batch_id == batch_id).order_by(Payout.created_at)
        )
        payouts = [self._to_payout_dto(row) for row in result.all()]
        logger.debug(f"Crypto batch '{batch_id}' collected '{len(payouts)}' payouts")
        return payouts

    # --- mapping ---
    @staticmethod
    def _to_payout_dto(row: Payout) -> PayoutDto:
        return PayoutDto(
            id=row.id,
            user_id=row.user_id,
            method=row.method,
            amount_kop=row.amount_kop,
            status=row.status,
            crypto_wallet=row.crypto_wallet,
            crypto_asset=row.crypto_asset,
            crypto_network=row.crypto_network,
            crypto_amount=row.crypto_amount,
            fx_rate=row.fx_rate,
            tx_hash=row.tx_hash,
            batch_id=row.batch_id,
            reject_reason=row.reject_reason,
            processed_at=row.processed_at,
            operator_id=row.operator_id,
            note=row.note,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
