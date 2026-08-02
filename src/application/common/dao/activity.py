from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class RecentActivityDao(Protocol):
    async def touch(self, user_id: int) -> None: ...

    async def forget(self, user_id: int) -> None:
        """Drop a user from the recent-activity board (they no longer exist)."""
        ...

    async def get_recent_ids(
        self,
        limit: int,
        excluded_ids: Sequence[int] = (),
    ) -> list[int]: ...
