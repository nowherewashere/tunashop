from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import ReferralDao, ReferralLedgerDao, SettingsDao
from src.application.common.uow import UnitOfWork
from src.application.dto import ReferralEventDto, TransactionDto, UserDto
from src.core.config import AppConfig
from src.core.enums import Currency


@dataclass(frozen=True)
class RecordReferralCommissionDto:
    user: UserDto  # the paying (referred) user
    transaction: TransactionDto


class RecordReferralCommission(Interactor[RecordReferralCommissionDto, None]):
    """Record a money commission on a referred user's real-money payment
    (referral spec §2 / §3.2). Replaces the legacy points/extra-days accrual.

    - **Single-tier:** only the first-level referrer earns (no MLM).
    - **Idempotent** on the payment id: a duplicate/retried webhook never double-credits.
    - **Anti-loop:** balance-funded payments never reach here (pay-with-balance bypasses
      the PSP path), so "no commission on balance payments" holds structurally.

    Recurring by design — this fires on *every* real-money payment (new + renewals),
    not just the first, because it runs on each successful ``ProcessPayment``.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        settings_dao: SettingsDao,
        referral_dao: ReferralDao,
        referral_ledger_dao: ReferralLedgerDao,
        config: AppConfig,
    ) -> None:
        self.uow = uow
        self.settings_dao = settings_dao
        self.referral_dao = referral_dao
        self.referral_ledger_dao = referral_ledger_dao
        self.config = config

    async def _execute(self, actor: UserDto, data: RecordReferralCommissionDto) -> None:
        settings = await self.settings_dao.get()
        if not settings.referral.enable:
            logger.info("Referral disabled; commission skipped")
            return

        tx = data.transaction
        if tx.plan_snapshot and tx.plan_snapshot.is_trial:
            logger.info(f"Commission skipped: transaction '{tx.id}' is a trial purchase")
            return
        if tx.pricing.is_free:
            logger.info(f"Commission skipped: transaction '{tx.id}' is free")
            return
        if tx.currency != Currency.RUB:
            # The balance ledger is in ₽. Commission on non-RUB payments (crypto/Stars)
            # needs an FX rate that is out of scope this iteration — skip, don't misprice.
            logger.info(
                f"Commission skipped: non-RUB currency '{tx.currency}' for transaction "
                f"'{tx.id}' (FX not configured)"
            )
            return

        # Single-tier: only the first-level referrer earns (referral spec §1).
        referral = await self.referral_dao.get_by_referred_id(data.user.id)
        if not referral:
            logger.info(f"{data.user.log} not referred; commission skipped")
            return

        rate_bp = self.config.referral.rate_bp
        payment_kop = int((tx.pricing.final_amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
        commission_kop = int(
            (Decimal(payment_kop) * Decimal(rate_bp) / Decimal(10000)).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )
        if commission_kop <= 0:
            logger.info(f"Commission <= 0 for transaction '{tx.id}'; skipped")
            return

        async with self.uow:
            inserted = await self.referral_ledger_dao.add_commission(
                ReferralEventDto(
                    referrer_id=referral.referrer.id,
                    referred_id=data.user.id,
                    payment_id=str(tx.payment_id),
                    payment_kop=payment_kop,
                    commission_kop=commission_kop,
                    rate_bp=rate_bp,
                )
            )
            await self.uow.commit()

        if inserted:
            # METRICS HOOK — this is the `referral_attributed` moment (metrics spec §4:
            # "referred user pays", carrying referrer_ref + payout_rub). When the metrics
            # layer lands, emit the event here (or add an @on_event listener) — the data
            # (referrer, referred, commission_kop) is all in scope.
            logger.info(
                f"Referral commission '{commission_kop}' kop recorded for referrer "
                f"'{referral.referrer.remna_name}' from '{data.user.log}' "
                f"(payment '{tx.payment_id}')"
            )
