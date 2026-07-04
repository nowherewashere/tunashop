from datetime import datetime
from typing import Protocol, runtime_checkable

from src.application.dto import OnboardingNudgeDto


@runtime_checkable
class OnboardingNudgeDao(Protocol):
    async def schedule(self, telegram_id: int, step: str, fire_at: datetime) -> None:
        """Insert a pending nudge, skipping if the (telegram_id, step) pair already
        exists in any status — so the whole chain fires at most once per user."""
        ...

    async def cancel_pending(self, telegram_id: int) -> None: ...

    async def get_due(self, now: datetime, limit: int = 100) -> list[OnboardingNudgeDto]: ...

    async def mark_sent(self, nudge_id: int, sent_at: datetime) -> None: ...

    async def mark_cancelled(self, nudge_id: int) -> None: ...

    async def sent_in_window(self, telegram_id: int, since: datetime) -> int: ...
