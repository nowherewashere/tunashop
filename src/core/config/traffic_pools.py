from typing import Final

from .base import BaseConfig

# Share of the quota that triggers the "почти всё" warning. Also the server-side
# `minTotalBytes` floor of the metering query, so one panel request per accounting
# window covers both the warning and the exhaustion verdict.
TRAFFIC_POOL_WARN_RATIO: Final[float] = 0.8

# How long a per-user pool reading is reused across renders. The panel flushes its
# bandwidth counters to the database roughly every two minutes, so a shorter window
# would only buy extra round trips — and the query is day-granular anyway, which makes
# consecutive reads within a minute identical by construction.
POOL_USAGE_CACHE_TTL: Final[int] = 60

# Distinct accounting windows in one pool past which the metering pass logs a warning.
# Every window costs one panel request on every tick, so this is the pass's request
# budget. The calendar strategies contribute one window each and MONTH_ROLLING at most
# one per anniversary day (31), so a healthy pool stays well under this; going past it
# means NO_RESET quotas dominate, whose window opens at each subscription's own creation
# date and so grows with signups rather than staying inside the calendar.
TRAFFIC_POOL_MAX_EXPECTED_WINDOWS: Final[int] = 40


class TrafficPoolsConfig(BaseConfig, env_prefix="TRAFFIC_POOLS_"):
    """Metered quotas on premium locations, on top of otherwise unlimited traffic.

    The panel has exactly one global traffic limit per user and none per squad/node,
    so the quota is metered and enforced here: a pool is an internal squad holding
    only premium nodes, usage is read from the 3.x squad bandwidth-stats endpoints,
    and exhaustion is applied by withdrawing that squad from the user until the
    period rolls over. The global ``trafficLimitBytes`` stays 0 — otherwise the panel
    would move the user to LIMITED *everywhere*.

    Shipped OFF (like Stars payouts and the support bridge): with ``enabled=false``
    the cron does nothing, the squad assignment paths behave exactly as before, and
    the public API omits the ``pools`` field.
    """

    enabled: bool = False
    # How far back the metering pass is willing to look when a period started long
    # ago (NO_RESET, or a very old rolling window). The panel query is bounded by
    # dates, so this caps an unbounded scan; usage older than this is not counted.
    #
    # Must clear the longest term a plan can sell, plus the snap back to the 1st of
    # the starting month: the 360-day plan reaches ~390 days, and the old 400 left so
    # little headroom that a yearly subscriber would have silently stopped being
    # metered near the end of their term.
    max_period_days: int = 460
    # Users per page of the squad-usage cursor. The panel caps this at 1000.
    page_size: int = 500
