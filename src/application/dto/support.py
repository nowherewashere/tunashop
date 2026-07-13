from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.infrastructure.database.models.support import (
    CHANNEL_SITE,
    CONVERSATION_OPEN,
)

from .base import BaseDto, TimestampMixin


@dataclass(kw_only=True)
class SupportConversationDto(BaseDto, TimestampMixin):
    user_id: int
    telegram_topic_id: Optional[int] = None
    status: str = CONVERSATION_OPEN
    last_user_channel: str = CHANNEL_SITE
    last_message_at: Optional[datetime] = None


@dataclass(kw_only=True)
class SupportMessageDto(BaseDto, TimestampMixin):
    conversation_id: int
    direction: str
    sender: str
    text: str
    source: str
    operator_user_id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    read_at: Optional[datetime] = None
