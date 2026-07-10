from typing import Protocol, runtime_checkable

from src.application.dto import PayoutDto


@runtime_checkable
class AccountMergeDao(Protocol):
    async def reassign_children(self, survivor_id: int, loser_id: int) -> list[PayoutDto]:
        """Repoint every child record owned by ``loser_id`` onto ``survivor_id``.

        Runs on the caller's session without committing, so it composes into a
        single merge transaction. Rows that would violate a per-user unique
        constraint on the survivor (a second `referred_id`, a promocode the
        survivor already redeemed, an OAuth provider already linked) are dropped
        rather than repointed, as are referral commissions earned *between* the two
        accounts (repointing them would mint a self-referral).

        Two survivor-side invariants are restored here as well: the loser's referral
        code is tombstoned onto the survivor (so shared links keep attributing), and
        the merged payouts are collapsed back to at most one open row. The payouts that
        had to be closed are returned, so the caller can notify their owner *after* the
        merge commits — this DAO has a session and nothing else.

        Every table with a user FK must be covered here: those FKs cascade on user
        delete, so anything omitted is silently destroyed when the loser row goes.
        Called by every merge direction, so a table added here is covered everywhere.
        """
        ...
