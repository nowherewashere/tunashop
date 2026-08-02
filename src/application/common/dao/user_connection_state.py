from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class UserConnectionStateDao(Protocol):
    async def is_connected_once(self, telegram_id: int) -> bool: ...

    async def mark_connected(self, telegram_id: int, at: datetime) -> None:
        """Upsert the row, flipping ``connected_once`` on and stamping the first
        connection time (only the first time)."""
        ...

    async def delete(self, telegram_id: int) -> bool:
        """Forget the user's connection milestones.

        Keyed by ``telegram_id`` with no FK to ``users``, so it survives a deleted
        account: the hub would greet a brand-new user with "уже подключался" and the
        trial timer would refuse to restart. True when a row was actually removed.
        """
        ...

    async def try_mark_trial_restarted(self, telegram_id: int, at: datetime) -> bool:
        """Atomically claim the one-time trial-timer restart.

        Returns ``True`` iff this call is the one that set ``trial_restarted_at``
        (i.e. it was still NULL), so the caller restarts the clock exactly once.
        """
        ...
