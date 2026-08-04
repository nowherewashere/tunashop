from typing import Final

from .base import BaseConfig

# Share of the quota that triggers the "почти всё" warning. Also the server-side
# `minTotalBytes` floor of the metering query, so one panel request per (pool, quota)
# covers both the warning and the exhaustion verdict.
TRAFFIC_POOL_WARN_RATIO: Final[float] = 0.8


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
    max_period_days: int = 400
    # Users per page of the squad-usage cursor. The panel caps this at 1000.
    page_size: int = 500
