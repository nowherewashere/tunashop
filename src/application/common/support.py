from typing import Optional, Protocol, runtime_checkable

from src.application.dto import SupportConversationDto, SupportMessageDto, UserDto


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
