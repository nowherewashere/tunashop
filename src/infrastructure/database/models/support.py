from datetime import datetime
from typing import Final, Literal, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin

# ---------------------------------------------------------------------------
# Unified support bridge (support spec / additive fork feature).
#
# One conversation per user, bridged to a Telegram forum topic in the operator
# supergroup. Website users and bot users both land in the same topic, so an
# operator answers every channel from a single Telegram interface. The DB is the
# source of truth for history (the site reads it); the Telegram topic is the
# operator's view + transport, not the store.
#
# Statuses / channels / directions are plain strings (not PG enums) to keep the
# whole feature a set of additive tables with no changes to the shared enum
# registry — mirroring `lifecycle_followups` / `referral_events`.
# ---------------------------------------------------------------------------

# support_conversations.status
CONVERSATION_OPEN: Final[str] = "open"
CONVERSATION_CLOSED: Final[str] = "closed"

# support_conversations.last_user_channel & support_messages.source
CHANNEL_SITE: Final[str] = "site"
CHANNEL_TELEGRAM: Final[str] = "telegram"

# support_messages.direction
DIRECTION_INBOUND: Final[str] = "inbound"  # user -> operator
DIRECTION_OUTBOUND: Final[str] = "outbound"  # operator -> user

# support_messages.sender
SENDER_USER: Final[str] = "user"
SENDER_OPERATOR: Final[str] = "operator"
SENDER_SYSTEM: Final[str] = "system"


def author_for_sender(sender: str) -> Literal["user", "operator", "system"]:
    """Map an internal ``sender`` to the three author roles the widget renders.

    Single source of truth for the mapping, shared by the HTTP history endpoint and
    the pub/sub publisher so the site sees one consistent `author` on every surface.
    """
    if sender == SENDER_OPERATOR:
        return "operator"
    if sender == SENDER_SYSTEM:
        return "system"
    return "user"


class SupportConversation(BaseSql, TimestampMixin):
    """A user's single support thread, mapped to one Telegram forum topic.

    One row per user (``user_id`` unique): the thread is long-lived and its
    ``status`` toggles between ``open`` and ``closed`` as the operator closes it and
    the user re-engages. The topic (``telegram_topic_id``) is created lazily on the
    first message and then reused for the lifetime of the thread, so the operator's
    history stays in one place.
    """

    __tablename__ = "support_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # One conversation per user, both channels folded into it (site + bot share the
    # same operator topic). Unique so get-or-create is race-safe via ON CONFLICT.
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    # message_thread_id of the forum topic in the operator supergroup; NULL until the
    # first message lazily creates the topic.
    telegram_topic_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=CONVERSATION_OPEN, server_default=CONVERSATION_OPEN
    )
    # The surface the user last wrote from — decides where an operator reply is pushed
    # (a site reply is read by polling; a telegram reply is also DM'd to the user).
    last_user_channel: Mapped[str] = mapped_column(
        String(16), default=CHANNEL_SITE, server_default=CHANNEL_SITE
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Reverse lookup on an operator reply: topic_id -> conversation.
        Index("ix_support_conversations_topic_id", "telegram_topic_id"),
    )


class SupportMessage(BaseSql, TimestampMixin):
    """One message in a conversation — the single source of truth for both channels.

    ``inbound`` = user -> operator, ``outbound`` = operator -> user. The site renders
    history from these rows and polls for new ones by ``id`` cursor, so the table
    carries everything the UI needs (author, text, time) without reaching into
    Telegram.
    """

    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("support_conversations.id", ondelete="CASCADE"),
    )
    direction: Mapped[str] = mapped_column(String(16))
    sender: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # site / telegram
    # The operator's local user id (attribution), when the sender is an operator.
    operator_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # message_id of the relayed/origin Telegram message, when there is one.
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Cursor pagination for the site poll: messages of a conversation after an id.
        Index("ix_support_messages_conversation_id_id", "conversation_id", "id"),
    )
