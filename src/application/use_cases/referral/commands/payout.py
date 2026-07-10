from dataclasses import dataclass
from typing import Optional

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
    PayoutMethodUnavailableError,
    PayoutNoTelegramError,
    ReferralError,
)
from src.core.utils.money import kop_to_stars
from src.infrastructure.database.models.referral_ledger import PAYOUT_METHOD_STARS


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


@dataclass(frozen=True)
class ChangeCryptoWalletDto:
    user: UserDto
    wallet: str


class ChangeCryptoPayoutWallet(Interactor[ChangeCryptoWalletDto, PayoutDto]):
    """Change the wallet on an already-requested crypto payout (tofix item 11).

    Allowed only while the payout is still ``requested`` — i.e. before the weekly batch
    or an operator moves it to ``processing``. The DAO update is guarded on that status,
    so a concurrent transition can't be clobbered; a lost race surfaces as
    ``PayoutLockedError``. Returns the updated open payout.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        referral_ledger_dao: ReferralLedgerDao,
    ) -> None:
        self.uow = uow
        self.referral_ledger_dao = referral_ledger_dao

    async def _execute(self, actor: UserDto, data: ChangeCryptoWalletDto) -> PayoutDto:
        wallet = data.wallet.strip()
        # Same light sanity check as RequestCryptoPayout; the operator verifies before sending.
        if len(wallet) < 20 or " " in wallet:
            raise ReferralError("Invalid crypto wallet address")

        async with self.uow:
            updated = await self.referral_ledger_dao.update_open_crypto_wallet(data.user.id, wallet)
            await self.uow.commit()
        if not updated:
            raise PayoutLockedError("No editable crypto payout to update")

        payout = await self.referral_ledger_dao.get_open_payout(data.user.id)
        if payout is None:  # taken into processing right after the update — treat as locked
            raise PayoutLockedError("Open payout vanished after wallet change")

        logger.info(f"{data.user.log} changed crypto payout wallet to '{wallet[:6]}…'")
        return payout


@dataclass(frozen=True)
class RequestStarsPayoutDto:
    user: UserDto
    # None → gift the whole balance (bot flow). A specific kopeck amount (≤ balance)
    # is supported for future partial payouts; it is clamped to the balance.
    amount_kop: Optional[int] = None


class RequestPayoutStars(Interactor[RequestStarsPayoutDto, PayoutDto]):
    """Request a Telegram Stars payout (spec §3.3 / §7.2).

    Converts the requested RUB amount to whole Stars at ``STARS_RUB_RATE`` (frozen on
    the row) and enqueues ``payouts{stars, requested}`` with the recipient snapshot.
    Preconditions: Stars enabled, a linked ``telegram_id`` (website-only users →
    crypto only), ``Баланс ≥ STARS_MIN_KOP``, balance ≥ 0, and no other open payout.
    Settlement is operator-assisted in beta (gift from the treasury, §5.5 seam).
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

    async def _execute(self, actor: UserDto, data: RequestStarsPayoutDto) -> PayoutDto:
        stars_cfg = self.config.stars
        if not stars_cfg.payout_enabled or stars_cfg.rub_rate <= 0:
            raise PayoutMethodUnavailableError("Stars payout is disabled or not configured")
        if data.user.telegram_id is None:
            raise PayoutNoTelegramError("Stars payout requires a linked Telegram account")

        summary = await self.get_referral_summary.system(GetReferralSummaryDto(data.user.id))
        if summary.has_open_payout:
            raise PayoutLockedError("A payout is already in progress")
        if summary.balance_kop < 0:
            raise BalanceNegativeError("Balance is negative; payout blocked")
        if summary.balance_kop < stars_cfg.min_kop:
            raise PayoutBelowMinimumError(
                f"Balance {summary.balance_kop} kop < stars min {stars_cfg.min_kop} kop"
            )

        # Gift whole Stars only; the RUB value actually withdrawn is stars × rate, so a
        # sub-Star remainder stays on the balance (WITHDRAWN math stays exact).
        rate = stars_cfg.rub_rate
        requested_kop = (
            summary.balance_kop
            if data.amount_kop is None
            else min(data.amount_kop, summary.balance_kop)
        )
        stars = kop_to_stars(requested_kop, rate)
        if stars <= 0:
            raise PayoutBelowMinimumError("Balance is below the price of a single Star")
        amount_kop = stars * rate

        # Snapshot the gift target: a searchable @username for the operator when there
        # is one, else the numeric id (still resolvable by MTProto later).
        recipient = (
            f"@{data.user.username}" if data.user.username else str(data.user.telegram_id)
        )

        async with self.uow:
            payout = await self.referral_ledger_dao.create_payout(
                PayoutDto(
                    user_id=data.user.id,
                    method=PAYOUT_METHOD_STARS,
                    amount_kop=amount_kop,
                    stars_amount=stars,
                    stars_rate=rate,
                    recipient_tg=recipient,
                    treasury_account=stars_cfg.treasury_account or None,
                )
            )
            await self.uow.commit()

        logger.info(
            f"{data.user.log} requested stars payout '{stars}' ⭐ "
            f"('{amount_kop}' kop @ '{rate}' kop/⭐) to '{recipient}'"
        )
        return payout
