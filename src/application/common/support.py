from typing import Any, Optional, Protocol, runtime_checkable

from src.application.dto import SupportConversationDto, SupportMessageDto, UserDto

# ---------------------------------------------------------------------------
# Real-time transport contract (Redis pub/sub -> SSE).
#
# Operator replies (and conversation status changes) are published on a per-user
# Redis channel; the site's SSE endpoint (`GET /support/stream`) subscribes to it
# and forwards each event, so the cabinet no longer polls `GET /support/messages`
# every few seconds. Both the publisher (infrastructure support service) and the
# consumer (web SSE endpoint) share this contract — keeping the channel name and
# the on-the-wire envelope defined in exactly one place. The builders take plain
# primitives so neither layer has to import the other's models.
# ---------------------------------------------------------------------------

# Envelope discriminator (the `type` field) — the SSE client switches on it.
SUPPORT_EVENT_MESSAGE = "message"
SUPPORT_EVENT_STATUS = "status"

_SUPPORT_EVENTS_CHANNEL_PREFIX = "support:events:"


def support_events_channel(user_id: int) -> str:
    """Per-user pub/sub channel carrying that user's live support events."""
    return f"{_SUPPORT_EVENTS_CHANNEL_PREFIX}{user_id}"


def build_message_event(*, id: int, author: str, text: str, created_at: str) -> dict[str, Any]:
    """A new-message event (mirrors the SupportMessageResponse shape under `message`)."""
    return {
        "type": SUPPORT_EVENT_MESSAGE,
        "message": {"id": id, "author": author, "text": text, "created_at": created_at},
    }


def build_status_event(status: str) -> dict[str, Any]:
    """A conversation-status change event (open / closed)."""
    return {"type": SUPPORT_EVENT_STATUS, "status": status}


@runtime_checkable
class SupportService(Protocol):
    """The bridge between a user (site or bot) and an operator in a Telegram topic.

    Both surfaces call ``ingest_from_user``; the operator group's message handler
    calls ``ingest_from_operator``. The DB holds the history; the forum topic is the
    operator's live view.
    """

    async def ingest_from_user(
        self, user: UserDto, text: str, channel: str
    ) -> SupportMessageDto:
        """Store a user's message and relay it into their operator topic.

        Creates the conversation + forum topic lazily on the first message. Raises
        ``SupportUnavailableError`` when support is disabled.
        """
        ...

    async def ingest_from_operator(
        self,
        topic_id: int,
        *,
        operator_telegram_id: int,
        text: str,
        telegram_message_id: int,
    ) -> bool:
        """Store an operator's reply and deliver it to the user.

        Returns ``False`` when ``topic_id`` maps to no conversation (a message in an
        unrelated topic), so the caller can ignore it.
        """
        ...

    async def close_by_topic(self, topic_id: int) -> bool:
        """Mark the conversation behind a topic closed. Returns False if unmapped."""
        ...

    async def post_card(self, topic_id: int) -> bool:
        """(Re)post the user card into a topic. Returns False if the topic is unmapped."""
        ...

    async def close_idle(self) -> int:
        """Auto-close conversations idle past the configured threshold; close their
        forum topics. Returns how many were closed. A new user message reopens one."""
        ...

    async def list_messages(
        self, user: UserDto, after_id: int = 0
    ) -> tuple[Optional[SupportConversationDto], list[SupportMessageDto]]:
        """The user's conversation + its messages (for the site history/poll)."""
        ...
