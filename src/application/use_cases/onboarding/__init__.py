from typing import Final

from src.application.common import Interactor

from .commands import (
    CancelOnboardingNudges,
    ProcessDueOnboardingNudges,
    ScheduleOnboardingNudges,
)

ONBOARDING_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    ScheduleOnboardingNudges,
    CancelOnboardingNudges,
    ProcessDueOnboardingNudges,
)
