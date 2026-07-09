from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP

from loguru import logger

from src.application.common import Interactor, Remnawave
from src.application.common.dao import PlanDao, ReferralLedgerDao, SubscriptionDao
from src.application.common.uow import UnitOfWork
from src.application.dto import BalanceSpendDto, PlanSnapshotDto, UserDto
from src.application.use_cases.referral.queries.summary import (
    GetReferralSummary,
    GetReferralSummaryDto,
)
from src.core.enums import Currency
from src.core.exceptions import (
    BalanceNegativeError,
    InsufficientBalanceError,
    PayoutLockedError,
    PlanError,
    PurchaseError,
)
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class PayWithBalanceDto:
    user: UserDto
    plan_id: int
    duration_days: int


@dataclass(frozen=True)
class PayWithBalanceResult:
    amount_kop: int
    new_expire_at: datetime
    balance_kop: int  # remaining balance after the spend


class PayWithBalance(Interactor[PayWithBalanceDto, PayWithBalanceResult]):
    """Pay for the user's own subscription from the referral balance (spec §3.4).

    Full-cover only: allowed iff ``Баланс ≥ plan price``. Records a ``balance_spend``
    (SPENT↑, Баланс↓) and extends the current subscription term. Generates **no**
    commission — this bypasses the PSP path entirely (anti-loop). Price is resolved
    server-side (base plan price, no discounts in beta) so the client can't set it.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        plan_dao: PlanDao,
        subscription_dao: SubscriptionDao,
        referral_ledger_dao: ReferralLedgerDao,
        remnawave: Remnawave,
        get_referral_summary: GetReferralSummary,
    ) -> None:
        self.uow = uow
        self.plan_dao = plan_dao
        self.subscription_dao = subscription_dao
        self.referral_ledger_dao = referral_ledger_dao
        self.remnawave = remnawave
        self.get_referral_summary = get_referral_summary

    async def _execute(self, actor: UserDto, data: PayWithBalanceDto) -> PayWithBalanceResult:
        user = data.user

        plan = await self.plan_dao.get_by_id(data.plan_id)
        if not plan or not plan.is_active or plan.is_trial:
            raise PlanError(f"Plan '{data.plan_id}' is not a purchasable plan")
        duration = plan.get_duration(data.duration_days)
        if not duration:
            raise PlanError(f"Plan '{data.plan_id}' has no '{data.duration_days}'-day duration")

        price_rub = duration.get_price(Currency.RUB)  # base price (no discounts in beta)
        price_kop = int((price_rub * 100).to_integral_value(rounding=ROUND_HALF_UP))

        # Gates (spec §3.4): full-cover, no open payout, balance ≥ 0.
        summary = await self.get_referral_summary.system(GetReferralSummaryDto(user.id))
        if summary.has_open_payout:
            raise PayoutLockedError("A payout is in progress; cannot pay with balance")
        if summary.balance_kop < 0:
            raise BalanceNegativeError("Balance is negative; pay-with-balance blocked")
        if summary.balance_kop < price_kop:
            raise InsufficientBalanceError(
                f"Balance {summary.balance_kop} kop < price {price_kop} kop"
            )

        plan_snapshot = PlanSnapshotDto.from_plan(plan, data.duration_days)

        async with self.uow:
            subscription = await self.subscription_dao.get_current(user.id)
            if not subscription:
                raise PurchaseError("No active subscription to extend with balance")

            base_date = max(subscription.expire_at, datetime_now())
            new_expire = base_date + timedelta(days=data.duration_days)

            subscription.expire_at = new_expire
            subscription.device_limit = plan_snapshot.device_limit
            subscription.traffic_limit = plan_snapshot.traffic_limit
            subscription.traffic_limit_strategy = plan_snapshot.traffic_limit_strategy
            subscription.tag = plan_snapshot.tag
            subscription.internal_squads = plan_snapshot.internal_squads
            subscription.external_squad = plan_snapshot.external_squad

            # Debit first, then extend — the Remnawave call happens before commit, so a
            # failure rolls back the spend (atomic-ish, mirroring AddSubscriptionDuration).
            await self.referral_ledger_dao.add_balance_spend(
                BalanceSpendDto(
                    user_id=user.id,
                    amount_kop=price_kop,
                    applied_term=data.duration_days,
                    remnawave_ref=str(subscription.user_remna_id),
                )
            )
            await self.remnawave.update_user(
                user=user,
                uuid=subscription.user_remna_id,
                subscription=subscription,
                reset_traffic=True,
            )
            subscription.plan_snapshot = plan_snapshot
            await self.subscription_dao.update(subscription)
            await self.uow.commit()

        new_balance = summary.balance_kop - price_kop
        logger.info(
            f"{user.log} paid {price_kop} kop from balance for '{data.duration_days}'d "
            f"of plan '{plan.name}'; balance now {new_balance} kop"
        )
        return PayWithBalanceResult(
            amount_kop=price_kop,
            new_expire_at=new_expire,
            balance_kop=new_balance,
        )
