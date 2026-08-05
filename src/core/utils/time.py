import time
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Optional

from remnapy.enums.users import TrafficLimitStrategy

from src.core.constants import TIMEZONE

START_TIME: int = int(time.time())


def datetime_now() -> datetime:
    return datetime.now(tz=TIMEZONE)


def get_uptime() -> int:
    uptime_seconds = int(time.time() - START_TIME)
    return uptime_seconds


def get_traffic_reset_delta(  # noqa: C901
    strategy: TrafficLimitStrategy,
    subscription_created_at: Optional[datetime] = None,
) -> timedelta:
    now = datetime_now()

    if strategy == TrafficLimitStrategy.NO_RESET:
        return timedelta(seconds=0)

    if strategy == TrafficLimitStrategy.DAY:
        next_day = now.date() + timedelta(days=1)
        reset_at = datetime.combine(next_day, datetime.min.time(), tzinfo=TIMEZONE)
        return reset_at - now

    if strategy == TrafficLimitStrategy.WEEK:
        weekday = now.weekday()
        days_until = (7 - weekday) % 7 or 7
        date_target = now.date() + timedelta(days=days_until)
        reset_at = datetime(
            date_target.year, date_target.month, date_target.day, 0, 5, 0, tzinfo=TIMEZONE
        )
        return reset_at - now

    if strategy == TrafficLimitStrategy.MONTH:
        year = now.year
        month = now.month + 1
        if month == 13:
            year += 1
            month = 1
        reset_at = datetime(year, month, 1, 0, 10, 0, tzinfo=TIMEZONE)
        return reset_at - now

    if strategy == TrafficLimitStrategy.MONTH_ROLLING:
        if subscription_created_at is None:
            raise ValueError("subscription_created_at is required for MONTH_ROLLING strategy")
        reset_day = subscription_created_at.day
        year = now.year
        month = now.month
        if now.day >= reset_day:
            month += 1
            if month == 13:
                year += 1
                month = 1
        try:
            reset_at = datetime(year, month, reset_day, 0, 10, 0, tzinfo=TIMEZONE)
        except ValueError:
            month += 1
            if month == 13:
                year += 1
                month = 1
            reset_at = datetime(year, month, 1, 0, 10, 0, tzinfo=TIMEZONE)
        return reset_at - now

    raise ValueError("Unsupported strategy")


def get_traffic_period_start(  # noqa: C901
    strategy: TrafficLimitStrategy,
    created_at: datetime,
    now: Optional[datetime] = None,
) -> datetime:
    """Start of the accounting window currently in force for ``strategy``.

    Counterpart of :func:`get_traffic_reset_delta`, which answers "how long until the
    counter resets"; this answers "since when has it been counting". Traffic pools need
    the boundary itself, not the distance to it, because the panel's bandwidth stats are
    queried over an explicit ``start``/``end`` range.

    Boundaries match the panel's own: midnight for DAY, Monday 00:05 for WEEK, the 1st
    at 00:10 for MONTH, the subscription's anniversary day at 00:10 for MONTH_ROLLING.
    Pair it with :func:`get_traffic_period_end` — as instants, that pair is exact by
    construction, so consecutive windows tile without gaps or overlap.
    (``get_traffic_reset_delta`` is *not* its exact inverse for MONTH_ROLLING in short
    months: it rolls a missing 31st to the 1st of the next month, while pools clamp it
    to the month's last day.)

    As *queried*, they do not tile — and cannot. The panel's bandwidth-stats endpoints
    take bare calendar dates (:data:`~src.core.constants.PANEL_DATE_FORMAT`) and widen
    them to ``startOf('day')``/``endOf('day')``, inclusive at both ends, so the times of
    day above are unrepresentable and the date on which a window opens falls inside that
    window *and* the one before it. The double-counted slice is the boundary's own
    offset: ten minutes at most for the calendar strategies, and for ``NO_RESET`` —
    whose window opens whenever the subscription was created — the rest of that calendar
    day. It errs against the user, never in their favour. None of this is a timezone
    problem: both sides work in UTC (:data:`~src.core.constants.TIMEZONE`), it is
    granularity alone. Callers that group or compare windows must do it at the same
    granularity to match — see :func:`to_panel_day_start`.

    ``NO_RESET`` has no boundary: the window opened when the subscription did and never
    closes, so ``created_at`` is returned verbatim.
    """
    now = now or datetime_now()

    if strategy == TrafficLimitStrategy.NO_RESET:
        return created_at

    if strategy == TrafficLimitStrategy.DAY:
        return datetime.combine(now.date(), datetime.min.time(), tzinfo=TIMEZONE)

    if strategy == TrafficLimitStrategy.WEEK:
        monday = now.date() - timedelta(days=now.weekday())
        start = datetime(monday.year, monday.month, monday.day, 0, 5, 0, tzinfo=TIMEZONE)
        if start > now:  # Monday, before 00:05 — still inside the previous week
            start -= timedelta(days=7)
        return start

    if strategy == TrafficLimitStrategy.MONTH:
        start = datetime(now.year, now.month, 1, 0, 10, 0, tzinfo=TIMEZONE)
        if start > now:  # the 1st, before 00:10
            start = _shift_month(start, -1)
        return start

    if strategy == TrafficLimitStrategy.MONTH_ROLLING:
        reset_day = created_at.day
        start = _rolling_anniversary(now.year, now.month, reset_day)
        if start > now:
            previous = _shift_month(datetime(now.year, now.month, 1, tzinfo=TIMEZONE), -1)
            start = _rolling_anniversary(previous.year, previous.month, reset_day)
        return start

    raise ValueError("Unsupported strategy")


def get_traffic_period_end(
    strategy: TrafficLimitStrategy,
    created_at: datetime,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """When the current window closes and the quota is handed back.

    ``None`` for ``NO_RESET`` — that quota is spent once and never returns. Exactly the
    next boundary after :func:`get_traffic_period_start`, so the value shown to the user
    as «обновится» is the same instant the metering pass rolls the window on.
    """
    now = now or datetime_now()
    start = get_traffic_period_start(strategy, created_at, now)

    if strategy == TrafficLimitStrategy.NO_RESET:
        return None
    if strategy == TrafficLimitStrategy.DAY:
        return start + timedelta(days=1)
    if strategy == TrafficLimitStrategy.WEEK:
        return start + timedelta(days=7)
    if strategy == TrafficLimitStrategy.MONTH:
        return _shift_month(start, 1)
    if strategy == TrafficLimitStrategy.MONTH_ROLLING:
        # Re-derive from the anniversary day rather than shifting `start`, whose day may
        # have been clamped by a short month (28 Feb must go back to the 31st, not stay).
        nxt = _shift_month(datetime(start.year, start.month, 1, tzinfo=TIMEZONE), 1)
        return _rolling_anniversary(nxt.year, nxt.month, created_at.day)

    raise ValueError("Unsupported strategy")


def to_panel_day_start(value: datetime) -> datetime:
    """``value`` truncated to the UTC day, the way a bandwidth-stats query will read it.

    The panel is sent bare dates and expands them itself, so any time of day carried by
    a window boundary is silently dropped in transit (see
    :func:`get_traffic_period_start`). Doing it here instead makes the value equal to
    the range the panel will actually count over — which matters wherever windows are
    compared or used as a dict key, because two boundaries the panel cannot tell apart
    must not be treated as two different queries.
    """
    return datetime.combine(
        value.astimezone(TIMEZONE).date(), datetime.min.time(), tzinfo=TIMEZONE
    )


def _shift_month(value: datetime, months: int) -> datetime:
    """Move ``value`` by whole months, clamping the day to the target month's length."""
    total = value.year * 12 + (value.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _rolling_anniversary(year: int, month: int, reset_day: int) -> datetime:
    """The rolling reset instant in a given month, clamped to short months.

    A subscription created on the 31st resets on the 30th/28th in months that have no
    31st — the same clamp ``get_traffic_reset_delta`` applies when it overflows.
    """
    day = min(reset_day, monthrange(year, month)[1])
    return datetime(year, month, day, 0, 10, 0, tzinfo=TIMEZONE)
