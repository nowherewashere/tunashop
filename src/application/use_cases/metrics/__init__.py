from typing import Final

from src.application.common import Interactor

from .commands import (
    ComputeDailyBusinessMetrics,
)

METRICS_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    ComputeDailyBusinessMetrics,
)
