from datetime import datetime, timedelta
from decimal import Decimal
from statistics import fmean
from typing import Any, Optional

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import EventsDao
from src.application.dto import UserDto
from src.application.dto.metrics import PaymentFeeRow
from src.core.metrics import FEE_CURVE_BUCKETS_RUB, FunnelStep, MetricEvent
from src.core.utils.time import datetime_now

# Rolling windows: daily volumes over 24h, but conversion/lifetime/plan-mix need a
# cohort that has had time to mature, so they roll over 30 days; funnel over 7.
_CONVERSION_WINDOW_DAYS = 30
_FUNNEL_WINDOW_DAYS = 7

_DAILY_EVENTS = (
    MetricEvent.TRIAL_STARTED,
    MetricEvent.FIRST_CONNECT,
    MetricEvent.TRIAL_CONVERTED,
    MetricEvent.PAYMENT,
    MetricEvent.SUBSCRIPTION_RENEWED,
    MetricEvent.CHURNED,
    MetricEvent.REFERRAL_ATTRIBUTED,
)

# Ordered funnel (spec §5): UI steps + the two server-detected business events.
_FUNNEL_ORDER = (
    FunnelStep.START,
    FunnelStep.DEVICE_SELECTED,
    FunnelStep.APP_INSTALL_SHOWN,
    FunnelStep.CONFIG_ISSUED,
    FunnelStep.FIRST_CONNECT,
    FunnelStep.TRIAL_CONVERTED,
)


class ComputeDailyBusinessMetrics(Interactor[None, dict[str, Any]]):
    """Daily offline rollup of the business hypotheses (metrics spec §8, §9).

    Reads the append-only ``events`` table and derives conversion, paying lifetime,
    plan mix, the real net/gross fee curve and funnel step deltas. No live dashboard
    (spec §7): it logs a structured summary and returns it, so the number lands in
    the logs and can be piped anywhere later without touching the user path.
    """

    required_permission = None

    def __init__(self, events_dao: EventsDao) -> None:
        self.events_dao = events_dao

    async def _execute(self, actor: UserDto, data: None) -> dict[str, Any]:
        now = datetime_now()
        day_ago = now - timedelta(days=1)
        cohort_since = now - timedelta(days=_CONVERSION_WINDOW_DAYS)
        funnel_since = now - timedelta(days=_FUNNEL_WINDOW_DAYS)

        daily_counts = {
            str(event_type): await self.events_dao.count(
                event_type=event_type, since=day_ago, until=now
            )
            for event_type in _DAILY_EVENTS
        }

        trials = await self.events_dao.count(
            event_type=MetricEvent.TRIAL_STARTED, since=cohort_since, until=now
        )
        conversions = await self.events_dao.count(
            event_type=MetricEvent.TRIAL_CONVERTED, since=cohort_since, until=now
        )

        plan_mix = await self.events_dao.group_by_property(
            event_type=MetricEvent.PAYMENT, prop_key="plan", since=cohort_since, until=now
        )
        fee_rows = await self.events_dao.payment_fee_rows(since=cohort_since, until=now)
        lifetimes = await self.events_dao.lifetime_days(since=cohort_since, until=now)

        summary: dict[str, Any] = {
            "generated_at": now.isoformat(),
            "daily_counts": daily_counts,
            "conversion": {
                "trial_started": trials,
                "trial_converted": conversions,
                "rate": round(conversions / trials, 4) if trials else None,
                "window_days": _CONVERSION_WINDOW_DAYS,
            },
            "paying_lifetime_days": {
                "avg": round(fmean(lifetimes), 1) if lifetimes else None,
                "samples": len(lifetimes),
            },
            "plan_mix": plan_mix,
            "fee_curve": self._fee_curve(fee_rows),
            "funnel": await self._funnel(funnel_since, now),
        }
        logger.info(f"[metrics] daily business rollup: {summary}")
        return summary

    def _fee_curve(self, rows: list[PaymentFeeRow]) -> list[dict[str, Any]]:
        """Real net/gross ratio by gross bucket (spec §8/§9) — replaces the model's
        2-point fee estimate. Only rows that actually carry a net are counted."""
        edges = list(FEE_CURVE_BUCKETS_RUB)
        # One accumulator per bucket + a final ">last" bucket.
        gross_sum = [Decimal(0)] * (len(edges) + 1)
        net_sum = [Decimal(0)] * (len(edges) + 1)
        counts = [0] * (len(edges) + 1)

        for row in rows:
            if row.net is None:
                continue
            index = next((i for i, edge in enumerate(edges) if row.gross <= edge), len(edges))
            gross_sum[index] += row.gross
            net_sum[index] += row.net
            counts[index] += 1

        labels = [f"<= {edge}" for edge in edges] + [f"> {edges[-1]}"]
        curve: list[dict[str, Any]] = []
        for index, label in enumerate(labels):
            if counts[index] == 0:
                continue
            curve.append(
                {
                    "bucket_rub": label,
                    "count": counts[index],
                    "net_gross_ratio": round(float(net_sum[index] / gross_sum[index]), 4),
                    "avg_fee_pct": round(
                        float((1 - net_sum[index] / gross_sum[index]) * 100), 2
                    ),
                }
            )
        return curve

    async def _funnel(self, since: datetime, until: datetime) -> dict[str, Any]:
        ui_counts = await self.events_dao.group_by_property(
            event_type=MetricEvent.FUNNEL_STEP, prop_key="step", since=since, until=until
        )
        first_connect = await self.events_dao.count(
            event_type=MetricEvent.FIRST_CONNECT, since=since, until=until
        )
        trial_converted = await self.events_dao.count(
            event_type=MetricEvent.TRIAL_CONVERTED, since=since, until=until
        )

        counts: dict[str, int] = dict(ui_counts)
        counts[FunnelStep.FIRST_CONNECT] = first_connect
        counts[FunnelStep.TRIAL_CONVERTED] = trial_converted

        steps: list[dict[str, Any]] = []
        previous: Optional[int] = None
        for step in _FUNNEL_ORDER:
            value = counts.get(step, 0)
            drop = None
            if previous is not None and previous > 0:
                drop = round((previous - value) / previous, 4)
            steps.append({"step": str(step), "count": value, "drop_from_prev": drop})
            previous = value
        return {"window_days": _FUNNEL_WINDOW_DAYS, "steps": steps}
