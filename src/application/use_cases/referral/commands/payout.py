from dataclasses import dataclass

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import ReferralLedgerDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PayoutDto, UserDto
from src.application.use_cases.referral.queries.summary import (
    GetReferralSummary,
    GetReferralSummaryDto,
)
from src.core.config import AppConfig
from src.core.exceptions import (
    BalanceNegativeError,
    PayoutBelowMinimumError,
    PayoutLockedError,
    ReferralError,
)


@dataclass(frozen=True)
class RequestCryptoPayoutDto:
    user: UserDto
    wallet: str


class RequestCryptoPayout(Interactor[RequestCryptoPayoutDto, PayoutDto]):
    """Request a crypto cash-out of the full balance (spec §3.3 / §7.1).

    Preconditions: ``Баланс ≥ REFERRAL_PAYOUT_MIN_KOP`` (1000 ₽), balance ≥ 0, and no
    other open payout (single-open lock). Enqueues ``payouts{crypto, requested}`` with
    the wallet snapshot; settlement happens in the weekly Monday batch (operator).
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_ledger_dao: ReferralLedgerDao,
        get_referral_summary: GetReferralSummary,
        config: AppConfig,
    ) -> None:
        self.uow = uow
        self.referral_ledger_dao = referral_ledger_dao
        self.get_referral_summary = get_referral_summary
        self.config = config

    async def _execute(self, actor: UserDto, data: RequestCryptoPayoutDto) -> PayoutDto:
        wallet = data.wallet.strip()
        # Light sanity check; the operator verifies the address before broadcasting.
        if len(wallet) < 20 or " " in wallet:
            raise ReferralError("Invalid crypto wallet address")

        summary = await self.get_referral_summary.system(GetReferralSummaryDto(data.user.id))
        if summary.has_open_payout:
            raise PayoutLockedError("A payout is already in progress")
        if summary.balance_kop < 0:
            raise BalanceNegativeError("Balance is negative; payout blocked")
        if summary.balance_kop < self.config.referral.payout_min_kop:
            raise PayoutBelowMinimumError(
                f"Balance {summary.balance_kop} kop < min {self.config.referral.payout_min_kop} kop"
            )

        async with self.uow:
            payout = await self.referral_ledger_dao.create_payout(
                PayoutDto(
                    user_id=data.user.id,
                    amount_kop=summary.balance_kop,
                    crypto_wallet=wallet,
                    crypto_asset=self.config.payout.crypto_asset,
                    crypto_network=self.config.payout.crypto_network,
                )
            )
            await self.uow.commit()

        logger.info(
            f"{data.user.log} requested crypto payout '{payout.amount_kop}' kop "
            f"to '{wallet[:6]}…' ({payout.crypto_asset}/{payout.crypto_network})"
        )
        return payout
