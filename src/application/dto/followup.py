from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleFollowupDto:
    """A single due lifecycle followup row, as read by the sweeper."""

    id: int
    telegram_id: int
    chain: str
    step: str
