from dataclasses import dataclass
from typing import Optional

from loguru import logger

from src.application.common import EventPublisher, Interactor
from src.application.common.dao import ReferralLedgerDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PayoutDto, UserDto
from src.application.events import (
    PayoutPaidEvent,
    PayoutProcessingEvent,
    PayoutRejectedEvent,
)
from src.application.use_cases.referral.queries.summary import (
    GetReferralSummary,
    GetReferralSummaryDto,
)
from src.core.exceptions import ReferralError
from src.core.utils.money import kop_to_rub, mask_wallet
from src.infrastructure.database.models.referral_ledger import (
    PAYOUT_OPEN_STATUSES,
    PAYOUT_REQUESTED,
)


@dataclass(frozen=True)
class PayoutActionDto:
    payout_id: int
    operator_id: int


@dataclass(frozen=True)
class CompletePayoutDto:
    payout_id: int
    operator_id: int
    tx_hash: str


@dataclass(frozen=True)
class RejectPayoutDto:
    payout_id: int
    operator_id: int
    reason: str


@dataclass(frozen=True)
class PayoutQueueItemDto:
    payout: PayoutDto
    user: Optional[UserDto]


async def _load_open_payout(dao: ReferralLedgerDao, payout_id: int) -> PayoutDto:
    payout = await dao.get_payout(payout_id)
    if not payout:
        raise ReferralError(f"Payout '{payout_id}' not found")
    if payout.status not in PAYOUT_OPEN_STATUSES:
        raise ReferralError(f"Payout '{payout_id}' is not open (status '{payout.status}')")
    return payout


class StartPayout(Interactor[PayoutActionDto, PayoutDto]):
    """Operator: move a requested payout to processing and notify the user."""

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_ledger_dao: ReferralLedgerDao,
        user_dao: UserDao,
        event_publisher: EventPublisher,
    ) -> None:
        self.uow = uow
        self.referral_ledger_dao = referral_ledger_dao
        self.user_dao = user_dao
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, data: PayoutActionDto) -> PayoutDto:
        payout = await _load_open_payout(self.referral_ledger_dao, data.payout_id)
        if payout.status != PAYOUT_REQUESTED:
            raise ReferralError(f"Payout '{data.payout_id}' is already processing")

        async with self.uow:
            await self.referral_ledger_dao.mark_processing(data.payout_id, data.operator_id)
            await self.uow.commit()

        user = await self.user_dao.get_by_id(payout.user_id)
        if user:
            await self.event_publisher.publish(
                PayoutProcessingEvent(user=user, amount=kop_to_rub(payout.amount_kop))
            )
        logger.info(f"{actor.log} started payout '{data.payout_id}'")
        return payout


class CompletePayout(Interactor[CompletePayoutDto, PayoutDto]):
    """Operator: mark a payout paid with its tx hash (WITHDRAWN += amount) and notify."""

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_ledger_dao: ReferralLedgerDao,
        user_dao: UserDao,
        event_publisher: EventPublisher,
    ) -> None:
        self.uow = uow
        self.referral_ledger_dao = referral_ledger_dao
        self.user_dao = user_dao
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, data: CompletePayoutDto) -> PayoutDto:
        payout = await _load_open_payout(self.referral_ledger_dao, data.payout_id)
        tx_hash = data.tx_hash.strip()
        if not tx_hash:
            raise ReferralError("tx_hash is required to mark a crypto payout paid")

        async with self.uow:
            await self.referral_ledger_dao.mark_paid(data.payout_id, data.operator_id, tx_hash)
            await self.uow.commit()

        user = await self.user_dao.get_by_id(payout.user_id)
        if user:
            await self.event_publisher.publish(
                PayoutPaidEvent(
                    user=user,
                    amount=kop_to_rub(payout.amount_kop),
                    wallet_short=mask_wallet(payout.crypto_wallet or ""),
                    tx_hash=tx_hash,
                )
            )
        logger.info(f"{actor.log} completed payout '{data.payout_id}' (tx '{tx_hash[:10]}…')")
        return payout


class RejectPayout(Interactor[RejectPayoutDto, PayoutDto]):
    """Operator: reject a payout (no ledger change; balance stays) and notify the user."""

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_ledger_dao: ReferralLedgerDao,
        user_dao: UserDao,
        event_publisher: EventPublisher,
        get_referral_summary: GetReferralSummary,
    ) -> None:
        self.uow = uow
        self.referral_ledger_dao = referral_ledger_dao
        self.user_dao = user_dao
        self.event_publisher = event_publisher
        self.get_referral_summary = get_referral_summary

    async def _execute(self, actor: UserDto, data: RejectPayoutDto) -> PayoutDto:
        payout = await _load_open_payout(self.referral_ledger_dao, data.payout_id)
        reason = data.reason.strip() or "—"

        async with self.uow:
            await self.referral_ledger_dao.mark_rejected(data.payout_id, data.operator_id, reason)
            await self.uow.commit()

        user = await self.user_dao.get_by_id(payout.user_id)
        if user:
            summary = await self.get_referral_summary.system(GetReferralSummaryDto(user.id))
            await self.event_publisher.publish(
                PayoutRejectedEvent(
                    user=user,
                    amount=kop_to_rub(payout.amount_kop),
                    reason=reason,
                    balance=kop_to_rub(summary.balance_kop),
                )
            )
        logger.info(f"{actor.log} rejected payout '{data.payout_id}': {reason}")
        return payout


@dataclass(frozen=True)
class GetPayoutQueueDto:
    status: str = PAYOUT_REQUESTED
    limit: int = 50
    offset: int = 0


class GetPayoutQueue(Interactor[GetPayoutQueueDto, list[PayoutQueueItemDto]]):
    """The operator queue view: payouts of a given status joined with their user."""

    required_permission = None

    def __init__(
        self,
        referral_ledger_dao: ReferralLedgerDao,
        user_dao: UserDao,
    ) -> None:
        self.referral_ledger_dao = referral_ledger_dao
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: GetPayoutQueueDto) -> list[PayoutQueueItemDto]:
        payouts = await self.referral_ledger_dao.list_payouts_by_status(
            data.status, limit=data.limit, offset=data.offset
        )
        items: list[PayoutQueueItemDto] = []
        for payout in payouts:
            user = await self.user_dao.get_by_id(payout.user_id)
            items.append(PayoutQueueItemDto(payout=payout, user=user))
        return items


class RunCryptoBatch(Interactor[None, int]):
    """Weekly Monday batch (spec §5.3): move all requested crypto payouts to
    processing under one batch id, then notify each user. The operator then
    broadcasts and marks each ``paid`` with its tx hash. Returns the batch size."""

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_ledger_dao: ReferralLedgerDao,
        user_dao: UserDao,
        event_publisher: EventPublisher,
    ) -> None:
        self.uow = uow
        self.referral_ledger_dao = referral_ledger_dao
        self.user_dao = user_dao
        self.event_publisher = event_publisher

    async def _execute(self, actor: UserDto, data: None) -> int:
        from src.core.utils.time import datetime_now  # noqa: PLC0415

        batch_id = datetime_now().strftime("%Y%m%d")

        async with self.uow:
            payouts = await self.referral_ledger_dao.collect_crypto_batch(batch_id)
            await self.uow.commit()

        for payout in payouts:
            user = await self.user_dao.get_by_id(payout.user_id)
            if user:
                await self.event_publisher.publish(
                    PayoutProcessingEvent(user=user, amount=kop_to_rub(payout.amount_kop))
                )
        logger.info(f"Crypto batch '{batch_id}': {len(payouts)} payout(s) moved to processing")
        return len(payouts)
