from dishka.integrations.taskiq import FromDishka, inject

from src.application.services import TrafficPoolMeteringService
from src.infrastructure.taskiq.broker import broker

# Premium-pool metering. Auto-discovered by the worker's
# `--tasks-pattern src/infrastructure/taskiq/tasks/*.py` glob.
#
# Cadence: every 15 minutes. The panel flushes bandwidth counters to its database
# roughly every 2 minutes, so anything faster mostly re-reads the same numbers; every
# 15 keeps the worst-case overshoot past the quota to a few minutes of one node's
# throughput. The pass is a no-op while TRAFFIC_POOLS_ENABLED is off.


@broker.task(schedule=[{"cron": "*/15 * * * *"}])
@inject(patch_module=True)
async def meter_traffic_pools_task(
    metering: FromDishka[TrafficPoolMeteringService],
) -> None:
    """Meter every active pool and apply the quota verdict."""
    await metering.run()
