from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from src.application.dto import SupportConversationDto, SupportMessageDto


@runtime_checkable
class SupportDao(Protocol):
    async def get_or_create(self, user_id: int, channel: str) -> SupportConversationDto:
        """Return the user's conversation, creating an open one if none exists.

        Race-safe via ``INSERT ... ON CONFLICT DO NOTHING`` on the unique ``user_id``
        so two concurrent first messages (e.g. site + bot) never create two rows.
        """
        ...

    async def get_by_user(self, user_id: int) -> Optional[SupportConversationDto]: ...

    async def get_by_id(self, conversation_id: int) -> Optional[SupportConversationDto]: ...

    async def get_by_topic_id(self, topic_id: int) -> Optional[SupportConversationDto]: ...

    async def try_set_topic(self, conversation_id: int, topic_id: int) -> bool:
        """Atomically claim the forum topic for a conversation.

        Returns ``True`` iff this call set ``telegram_topic_id`` (it was still NULL),
        so a lost race can delete its redundant topic — the same atomic-claim pattern
        as ``UserConnectionStateDao.try_mark_trial_restarted``.
        """
        ...

    async def set_status(self, conversation_id: int, status: str) -> None: ...

    async def close_idle(self, before: datetime) -> list[SupportConversationDto]:
        """Close every OPEN conversation whose last message is older than ``before``;
        return the rows that were closed (with their topic ids), so the caller can
        close their forum topics."""
        ...

    async def touch(self, conversation_id: int, channel: str, at: datetime) -> None:
        """Record the last inbound message time + the channel it came from."""
        ...

    async def add_message(
        self,
        conversation_id: int,
        *,
        direction: str,
        sender: str,
        text: str,
        source: str,
        operator_user_id: Optional[int] = None,
        telegram_message_id: Optional[int] = None,
    ) -> SupportMessageDto: ...

    async def list_messages(
        self,
        conversation_id: int,
        after_id: int = 0,
        limit: int = 200,
    ) -> list[SupportMessageDto]:
        """Messages of a conversation, ascending by id.

        ``after_id > 0`` returns messages newer than the cursor (the site poll path);
        ``after_id == 0`` returns the last ``limit`` messages (the initial load).
        """
        ...
