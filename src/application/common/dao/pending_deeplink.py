from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class PendingDeeplinkDao(Protocol):
    """A ``/start <payload>`` that a gate interrupted before its handler ran.

    The rules / channel gates answer with their own prompt and drop the update, so a
    deep link opened by a first-time user is simply lost — the payload is never seen
    by the router. Parking it here lets the flow resume the moment the gate is
    satisfied, instead of dumping the person in the main menu with nothing explained.

    One entry per Telegram user: a person can only be looking at one prompt at a time,
    and a newer deep link should replace an older one.
    """

    async def remember(self, telegram_id: int, payload: str, ttl: int) -> None: ...

    async def take(self, telegram_id: int, prefix: str) -> Optional[str]:
        """Claim the parked deep link if it belongs to ``prefix``, returning what
        follows it (i.e. the flow's own payload).

        Prefixed rather than "give me whatever is parked": every caller is one flow
        resuming itself, and a flow must never consume a deep link meant for another.
        Read and delete in one step, so an interrupted link is resumed at most once.
        """
        ...
