from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingNudgeDto:
    """A single due pre-connect nudge row, as read by the sweeper."""

    id: int
    telegram_id: int
    step: str
