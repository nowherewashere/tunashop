from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from src.application.common.dao import SupportDao
from src.application.dto import SupportConversationDto, SupportMessageDto
from src.infrastructure.database.models.support import (
    CONVERSATION_CLOSED,
    CONVERSATION_OPEN,
    SupportConversation,
    SupportMessage,
)

from .base import BaseDaoImpl


def to_conversation_dto(row: SupportConversation) -> SupportConversationDto:
    return SupportConversationDto(
        id=row.id,
        user_id=row.user_id,
        telegram_topic_id=row.telegram_topic_id,
        status=row.status,
        last_user_channel=row.last_user_channel,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def to_message_dto(row: SupportMessage) -> SupportMessageDto:
    return SupportMessageDto(
        id=row.id,
        conversation_id=row.conversation_id,
        direction=row.direction,
        sender=row.sender,
        text=row.text,
        source=row.source,
        operator_user_id=row.operator_user_id,
        telegram_message_id=row.telegram_message_id,
        read_at=row.read_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SupportDaoImpl(BaseDaoImpl, SupportDao):
    async def get_or_create(self, user_id: int, channel: str) -> SupportConversationDto:
        stmt = (
            insert(SupportConversation)
            .values(user_id=user_id, status=CONVERSATION_OPEN, last_user_channel=channel)
            .on_conflict_do_nothing(index_elements=["user_id"])
            .returning(SupportConversation)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            # Lost the insert race (or the row already existed) — read the existing one.
            row = await self.session.scalar(
                select(SupportConversation).where(SupportConversation.user_id == user_id)
            )
        assert row is not None
        return to_conversation_dto(row)

    async def get_by_user(self, user_id: int) -> Optional[SupportConversationDto]:
        row = await self.session.scalar(
            select(SupportConversation).where(SupportConversation.user_id == user_id)
        )
        return to_conversation_dto(row) if row else None

    async def get_by_id(self, conversation_id: int) -> Optional[SupportConversationDto]:
        row = await self.session.scalar(
            select(SupportConversation).where(SupportConversation.id == conversation_id)
        )
        return to_conversation_dto(row) if row else None

    async def get_by_topic_id(self, topic_id: int) -> Optional[SupportConversationDto]:
        row = await self.session.scalar(
            select(SupportConversation).where(
                SupportConversation.telegram_topic_id == topic_id
            )
        )
        return to_conversation_dto(row) if row else None

    async def try_set_topic(self, conversation_id: int, topic_id: int) -> bool:
        result = await self.session.execute(
            update(SupportConversation)
            .where(
                SupportConversation.id == conversation_id,
                SupportConversation.telegram_topic_id.is_(None),
            )
            .values(telegram_topic_id=topic_id)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def set_status(self, conversation_id: int, status: str) -> None:
        await self.session.execute(
            update(SupportConversation)
            .where(SupportConversation.id == conversation_id)
            .values(status=status)
        )

    async def close_idle(self, before: datetime) -> list[SupportConversationDto]:
        rows = (
            await self.session.scalars(
                update(SupportConversation)
                .where(
                    SupportConversation.status == CONVERSATION_OPEN,
                    SupportConversation.last_message_at.is_not(None),
                    SupportConversation.last_message_at < before,
                )
                .values(status=CONVERSATION_CLOSED)
                .returning(SupportConversation)
            )
        ).all()
        return [to_conversation_dto(row) for row in rows]

    async def touch(self, conversation_id: int, channel: str, at: datetime) -> None:
        await self.session.execute(
            update(SupportConversation)
            .where(SupportConversation.id == conversation_id)
            .values(last_user_channel=channel, last_message_at=at)
        )

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
    ) -> SupportMessageDto:
        stmt = (
            insert(SupportMessage)
            .values(
                conversation_id=conversation_id,
                direction=direction,
                sender=sender,
                text=text,
                source=source,
                operator_user_id=operator_user_id,
                telegram_message_id=telegram_message_id,
            )
            .returning(SupportMessage)
        )
        row = (await self.session.execute(stmt)).scalar_one()
        return to_message_dto(row)

    async def list_messages(
        self,
        conversation_id: int,
        after_id: int = 0,
        limit: int = 200,
    ) -> list[SupportMessageDto]:
        if after_id > 0:
            rows = (
                await self.session.scalars(
                    select(SupportMessage)
                    .where(
                        SupportMessage.conversation_id == conversation_id,
                        SupportMessage.id > after_id,
                    )
                    .order_by(SupportMessage.id.asc())
                    .limit(limit)
                )
            ).all()
            return [to_message_dto(row) for row in rows]

        # Initial load: take the newest `limit`, then present them oldest-first.
        rows = (
            await self.session.scalars(
                select(SupportMessage)
                .where(SupportMessage.conversation_id == conversation_id)
                .order_by(SupportMessage.id.desc())
                .limit(limit)
            )
        ).all()
        return [to_message_dto(row) for row in reversed(rows)]
