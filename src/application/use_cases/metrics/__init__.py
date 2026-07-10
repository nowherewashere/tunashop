from typing import Final

from src.application.common import Interactor

from .commands import (
    ComputeDailyBusinessMetrics,
    ComputeNodeHealth,
    RunNodeProbes,
)

METRICS_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    ComputeDailyBusinessMetrics,
    ComputeNodeHealth,
    RunNodeProbes,
)
