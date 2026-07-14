from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from loguru import logger

from src.application.dto import SubscriptionDto
from src.core.enums import Currency
from src.core.utils.converters import days_to_datetime
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class ChangeExpiryDto:
    """Result of a plan-change expiry recalculation.

    ``bonus_days`` is the number of extra days credited on top of the new plan's
    duration. ``basis`` records which branch produced the result (for logging /
    debugging), never used for control flow downstream.
    """

    new_expire: datetime
    bonus_days: int
    basis: str


class SubscriptionProrationService:
    """Recalculate a subscription's expiry when the user switches to another plan.

    Model (chosen by product): the user pays the **full** price of the new plan, and
    the remaining monetary value of the current plan is converted into extra days of
    the new plan::

        remaining_value = remaining_days * (old_paid_price / old_paid_duration)
        bonus_days      = floor(remaining_value / (new_paid_price / new_duration))
        new_expire      = now + new_duration + bonus_days

    Both sides use the amount **actually paid** (captured in ``PlanSnapshotDto.price``
    for the old plan, passed in for the new one), so discounts are respected on both
    ends and there is never a negative charge.

    Guards keep the result sane in every edge case — see ``compute_change_expiry``.
    Pure and deterministic: no I/O, safe to call inside or outside a transaction and
    idempotent for a given input.
    """

    def compute_change_expiry(
        self,
        current: SubscriptionDto,
        new_duration: int,
        new_price: Optional[Decimal],
        new_currency: Optional[Currency],
        now: Optional[datetime] = None,
    ) -> ChangeExpiryDto:
        now = now or datetime_now()

        # New plan is unlimited (0-day duration): expiry is the sentinel far-future
        # date; there is nothing to prorate onto an unlimited term.
        if new_duration == 0:
            return ChangeExpiryDto(days_to_datetime(0), 0, "unlimited_target")

        # Trial source: the user paid nothing, so there is no value to carry — start a
        # fresh term (matches the prior trial-conversion behaviour).
        if current.is_trial:
            return ChangeExpiryDto(now + timedelta(days=new_duration), 0, "trial_source")

        # Unlimited source: remaining time is effectively infinite; do not inflate the
        # new term with a nonsensical bonus.
        if current.is_unlimited:
            return ChangeExpiryDto(now + timedelta(days=new_duration), 0, "unlimited_source")

        remaining_seconds = (current.expire_at - now).total_seconds()

        # Expired subscription: no remaining value, plain fresh term.
        if remaining_seconds <= 0:
            return ChangeExpiryDto(now + timedelta(days=new_duration), 0, "expired")

        old = current.plan_snapshot

        # No monetary basis to compare (legacy snapshot without a price, a free/admin/
        # promo change with no new price, or a cross-currency purchase we can't compare
        # without FX): fall back to preserving the user's remaining days verbatim so no
        # paid time is ever lost. Whole-day floor via timedelta(days=...).
        if (
            old.price is None
            or old.price_currency is None
            or old.duration <= 0
            or old.price <= 0
            or new_price is None
            or new_price <= 0
            or new_currency is None
            or old.price_currency != new_currency
        ):
            base = max(current.expire_at, now)
            stacked = (base - now).days
            new_expire = base + timedelta(days=new_duration)
            logger.debug(
                f"Proration fallback (stack days): +{stacked} preserved days, "
                f"new_duration={new_duration}"
            )
            return ChangeExpiryDto(new_expire, max(0, stacked), "fallback_stack")

        remaining_frac = Decimal(str(remaining_seconds)) / Decimal(86400)
        old_daily = old.price / Decimal(old.duration)
        new_daily = new_price / Decimal(new_duration)
        remaining_value = remaining_frac * old_daily

        # Floor once, at the end, so we neither overpay days nor lose ~a day to an
        # early floor of the remaining time.
        bonus_days = int((remaining_value / new_daily).to_integral_value(rounding=ROUND_DOWN))
        bonus_days = max(0, bonus_days)
        new_expire = now + timedelta(days=new_duration + bonus_days)
        logger.debug(
            f"Proration value->days: remaining_value={remaining_value} "
            f"({old.price_currency}), bonus_days={bonus_days}, new_duration={new_duration}"
        )
        return ChangeExpiryDto(new_expire, bonus_days, "value_to_days")
