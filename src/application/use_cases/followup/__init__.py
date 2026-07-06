from typing import Final

from src.application.common import Interactor

from .commands import ProcessDueLifecycleFollowups

FOLLOWUP_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    ProcessDueLifecycleFollowups,
)
