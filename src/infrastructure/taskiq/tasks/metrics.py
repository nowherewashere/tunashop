from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.metrics.commands import (
    ComputeDailyBusinessMetrics,
)
from src.infrastructure.taskiq.broker import broker

# Offline computation layer (metrics spec §8): read-only rollups over the
# append-only `events` table. Auto-discovered by the worker's
# `--tasks-pattern src/infrastructure/taskiq/tasks/*.py` glob.


@broker.task(schedule=[{"cron": "17 3 * * *"}])
@inject(patch_module=True)
async def compute_daily_business_metrics_task(
    compute: FromDishka[ComputeDailyBusinessMetrics],
) -> None:
    """Daily business rollup (conversion, lifetime, plan mix, fee curve, funnel)."""
    await compute.system()
