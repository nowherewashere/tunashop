from typing import Protocol, runtime_checkable


@runtime_checkable
class AccountMergeDao(Protocol):
    async def reassign_children(self, survivor_id: int, loser_id: int) -> None:
        """Repoint every child record owned by ``loser_id`` onto ``survivor_id``.

        Runs on the caller's session without committing, so it composes into a
        single merge transaction. Rows that would violate a per-user unique
        constraint on the survivor (a second `referred_id`, a promocode the
        survivor already redeemed, an OAuth provider already linked) are dropped
        rather than repointed.
        """
        ...
