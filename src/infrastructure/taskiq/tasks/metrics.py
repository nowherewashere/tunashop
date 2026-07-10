from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.metrics.commands import (
    ComputeDailyBusinessMetrics,
    ComputeNodeHealth,
    RunNodeProbes,
)
from src.infrastructure.taskiq.broker import broker

# Offline computation layer (metrics spec §8): all read-only rollups over the
# append-only `events` table + the light active probe. Auto-discovered by the
# worker's `--tasks-pattern src/infrastructure/taskiq/tasks/*.py` glob.


@broker.task(schedule=[{"cron": "17 3 * * *"}])
@inject(patch_module=True)
async def compute_daily_business_metrics_task(
    compute: FromDishka[ComputeDailyBusinessMetrics],
) -> None:
    """Daily business rollup (conversion, lifetime, plan mix, fee curve, funnel)."""
    await compute.system()


@broker.task(schedule=[{"cron": "*/10 * * * *"}])
@inject(patch_module=True)
async def compute_node_health_task(
    compute: FromDishka[ComputeNodeHealth],
) -> None:
    """Health rollup + threshold alert per (node × protocol), every 10 minutes."""
    await compute.system()


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
@inject(patch_module=True)
async def run_node_probes_task(
    run_probes: FromDishka[RunNodeProbes],
) -> None:
    """Light active reachability probe per node, every 5 minutes (feeds /status)."""
    await run_probes.system()
