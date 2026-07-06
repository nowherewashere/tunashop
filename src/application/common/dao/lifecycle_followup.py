from datetime import datetime
from typing import Protocol, runtime_checkable

from src.application.dto import LifecycleFollowupDto


@runtime_checkable
class LifecycleFollowupDao(Protocol):
    async def schedule(
        self, telegram_id: int, chain: str, step: str, fire_at: datetime
    ) -> None:
        """Arm one followup step. Idempotent per ``(telegram_id, chain, step)`` in
        any status, so re-arming never duplicates or resets a chain."""
        ...

    async def cancel_chain(self, telegram_id: int, chain: str) -> None: ...

    async def cancel_all_pending(self, telegram_id: int) -> None: ...

    async def get_due(
        self, now: datetime, limit: int = 100
    ) -> list[LifecycleFollowupDto]: ...

    async def mark_sent(self, followup_id: int, sent_at: datetime) -> None: ...

    async def mark_cancelled(self, followup_id: int) -> None: ...

    async def sent_in_window(self, telegram_id: int, since: datetime) -> int: ...
