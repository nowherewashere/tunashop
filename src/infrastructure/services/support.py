import html
from datetime import timedelta
from typing import Any, Awaitable, Callable, Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from src.application.common import Notifier, SupportService
from src.application.common.dao import (
    SubscriptionDao,
    SupportDao,
    TransactionDao,
    UserDao,
)
from src.application.common.uow import UnitOfWork
from src.application.dto import (
    MessagePayloadDto,
    SupportConversationDto,
    SupportMessageDto,
    UserDto,
)
from src.core.config import AppConfig
from src.core.constants import SUPPORT_CB_CLOSE, SUPPORT_CB_DEVICES
from src.core.enums import TransactionStatus
from src.core.exceptions import SupportUnavailableError
from src.core.utils.time import datetime_now
from src.infrastructure.database.models.support import (
    CHANNEL_TELEGRAM,
    CONVERSATION_CLOSED,
    CONVERSATION_OPEN,
    DIRECTION_INBOUND,
    DIRECTION_OUTBOUND,
    SENDER_OPERATOR,
    SENDER_USER,
)

# Telegram forum-topic name hard limit.
_TOPIC_NAME_MAX = 128


class SupportServiceImpl(SupportService):
    """Bridges site/bot users and operators through Telegram forum topics.

    The DB is the source of truth (the site reads it); the operator supergroup's
    topics are the live operator interface. One conversation (= one topic) per user
    carries both channels.
    """

    def __init__(
        self,
        bot: Bot,
        notifier: Notifier,
        uow: UnitOfWork,
        support_dao: SupportDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        transaction_dao: TransactionDao,
        config: AppConfig,
    ) -> None:
        self.bot = bot
        self.notifier = notifier
        self.uow = uow
        self.support_dao = support_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.transaction_dao = transaction_dao
        self.config = config

    @property
    def _group_id(self) -> int:
        group_id = self.config.support.group_id
        if group_id is None:
            raise SupportUnavailableError
        return group_id

    async def ingest_from_user(
        self, user: UserDto, text: str, channel: str
    ) -> SupportMessageDto:
        if not self.config.support.is_active:
            raise SupportUnavailableError

        reopened = False
        async with self.uow:
            conv = await self.support_dao.get_or_create(user.id, channel)
            if conv.status == CONVERSATION_CLOSED:
                await self.support_dao.set_status(conv.id, CONVERSATION_OPEN)
                conv.status = CONVERSATION_OPEN
                reopened = True
            await self.uow.commit()

        conv = await self._ensure_topic(conv, user)

        if reopened and conv.telegram_topic_id is not None:
            # The operator had closed the topic; a new message reopens the same thread
            # so history stays in one place, and a fresh user card is posted so the
            # operator sees the current state at the start of every new session.
            await self._safe_topic_op(self.bot.reopen_forum_topic, conv.telegram_topic_id)
            await self._post_header(conv.telegram_topic_id, user)

        async with self.uow:
            message = await self.support_dao.add_message(
                conv.id,
                direction=DIRECTION_INBOUND,
                sender=SENDER_USER,
                text=text,
                source=channel,
            )
            await self.support_dao.touch(conv.id, channel, datetime_now())
            await self.uow.commit()

        if conv.telegram_topic_id is not None:
            await self._relay_to_topic(conv.telegram_topic_id, text)
        return message

    async def ingest_from_operator(
        self,
        topic_id: int,
        *,
        operator_telegram_id: int,
        text: str,
        telegram_message_id: int,
    ) -> bool:
        conv = await self.support_dao.get_by_topic_id(topic_id)
        if conv is None:
            return False

        operator = await self.user_dao.get_by_telegram_id(operator_telegram_id)
        async with self.uow:
            await self.support_dao.add_message(
                conv.id,
                direction=DIRECTION_OUTBOUND,
                sender=SENDER_OPERATOR,
                text=text,
                source=CHANNEL_TELEGRAM,
                operator_user_id=operator.id if operator else None,
                telegram_message_id=telegram_message_id,
            )
            await self.uow.commit()

        # Site users read the reply by polling (it is already stored). Telegram users
        # also get it as a DM — deliver only to the channel the user last wrote from so
        # a site conversation does not ping the user's private chat.
        if conv.last_user_channel == CHANNEL_TELEGRAM:
            target = await self.user_dao.get_by_id(conv.user_id)
            if target is not None and target.telegram_id is not None:
                await self.notifier.notify_user(
                    user=target,
                    payload=MessagePayloadDto(
                        i18n_key="raw-message",
                        # notify_user sends with HTML parse mode; escape so an operator's
                        # literal '<' etc. is not read as a (broken) entity.
                        i18n_kwargs={"content": html.escape(text)},
                        delete_after=None,
                    ),
                )
        return True

    async def close_by_topic(self, topic_id: int) -> bool:
        conv = await self.support_dao.get_by_topic_id(topic_id)
        if conv is None:
            return False
        async with self.uow:
            await self.support_dao.set_status(conv.id, CONVERSATION_CLOSED)
            await self.uow.commit()
        await self._safe_topic_op(self.bot.close_forum_topic, topic_id)
        return True

    async def close_idle(self) -> int:
        if not self.config.support.is_active:
            return 0
        minutes = self.config.support.idle_close_minutes
        if minutes <= 0:
            return 0
        before = datetime_now() - timedelta(minutes=minutes)
        async with self.uow:
            closed = await self.support_dao.close_idle(before)
            await self.uow.commit()
        for conv in closed:
            if conv.telegram_topic_id is not None:
                await self._safe_topic_op(self.bot.close_forum_topic, conv.telegram_topic_id)
        if closed:
            logger.info(f"Support: auto-closed {len(closed)} idle conversation(s)")
        return len(closed)

    async def post_card(self, topic_id: int) -> bool:
        conv = await self.support_dao.get_by_topic_id(topic_id)
        if conv is None:
            return False
        user = await self.user_dao.get_by_id(conv.user_id)
        if user is None:
            return False
        await self._post_header(topic_id, user)
        return True

    async def list_messages(
        self, user: UserDto, after_id: int = 0
    ) -> tuple[Optional[SupportConversationDto], list[SupportMessageDto]]:
        conv = await self.support_dao.get_by_user(user.id)
        if conv is None:
            return None, []
        messages = await self.support_dao.list_messages(conv.id, after_id=after_id)
        return conv, messages

    # --- internals ---------------------------------------------------------

    async def _ensure_topic(
        self, conv: SupportConversationDto, user: UserDto
    ) -> SupportConversationDto:
        if conv.telegram_topic_id is not None:
            return conv

        topic = await self.bot.create_forum_topic(
            chat_id=self._group_id, name=self._topic_name(user)
        )
        async with self.uow:
            won = await self.support_dao.try_set_topic(conv.id, topic.message_thread_id)
            await self.uow.commit()

        if won:
            conv.telegram_topic_id = topic.message_thread_id
            await self._post_header(topic.message_thread_id, user)
            return conv

        # Lost the create race (a concurrent first message already made a topic): drop
        # this redundant one and adopt the winner's.
        await self._safe_topic_op(self.bot.delete_forum_topic, topic.message_thread_id)
        refreshed = await self.support_dao.get_by_id(conv.id)
        return refreshed or conv

    def _topic_name(self, user: UserDto) -> str:
        return f"{user.name} · #{user.id}"[:_TOPIC_NAME_MAX]

    async def _post_header(self, topic_id: int, user: UserDto) -> None:
        lines = [f"🎫 <b>{html.escape(user.name)}</b> · <code>#{user.id}</code>"]
        if user.username:
            lines.append(f"Telegram: @{html.escape(user.username)}")
        elif user.telegram_id is not None:
            lines.append(f"Telegram ID: <code>{user.telegram_id}</code>")
        if user.email:
            lines.append(f"Email: {html.escape(user.email)}")
        lines.append("————")
        lines.append(await self._render_subscription(user.id))
        lines.append(await self._render_payments(user.id))

        try:
            await self.bot.send_message(
                chat_id=self._group_id,
                message_thread_id=topic_id,
                text="\n".join(lines),
                reply_markup=self._operator_keyboard(),
                disable_web_page_preview=True,
            )
        except Exception as error:
            logger.warning(f"Support: failed to post topic header for user {user.id}: {error}")

    @staticmethod
    def _operator_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🖥 Устройства", callback_data=SUPPORT_CB_DEVICES),
                    InlineKeyboardButton(text="🔒 Закрыть", callback_data=SUPPORT_CB_CLOSE),
                ]
            ]
        )

    async def _render_subscription(self, user_id: int) -> str:
        subscription = await self.subscription_dao.get_current(user_id)
        if subscription is None:
            return "💳 Подписка: нет"
        if subscription.is_expired:
            state = "истекла"
        elif subscription.is_trial:
            state = "триал"
        else:
            state = "активна"
        plan = html.escape(subscription.plan_snapshot.name or "—")
        return f"💳 {plan} · {state} · до {subscription.expire_at:%d.%m.%Y}"

    async def _render_payments(self, user_id: int) -> str:
        transactions = await self.transaction_dao.get_by_user(user_id)
        completed = [t for t in transactions if t.status == TransactionStatus.COMPLETED]
        completed.sort(key=lambda t: t.created_at or datetime_now(), reverse=True)
        if not completed:
            return "💰 Платежи: нет"
        rows = [f"💰 Платежи (последние {min(3, len(completed))}):"]
        for t in completed[:3]:
            when = f"{t.created_at:%d.%m.%y}" if t.created_at else "—"
            rows.append(f" • {when} · {t.pricing.final_amount:.0f} {t.currency.value}")
        return "\n".join(rows)

    async def _relay_to_topic(self, topic_id: int, text: str) -> None:
        try:
            await self.bot.send_message(
                chat_id=self._group_id,
                message_thread_id=topic_id,
                text=text,
                # User text is literal — never interpret it as HTML/Markdown.
                parse_mode=None,
                disable_web_page_preview=True,
            )
        except Exception as error:
            logger.warning(f"Support: failed to relay message to topic {topic_id}: {error}")

    async def _safe_topic_op(
        self, op: Callable[..., Awaitable[Any]], topic_id: int
    ) -> None:
        """Best-effort forum-topic side effect (open/close/reopen/delete)."""
        try:
            await op(chat_id=self._group_id, message_thread_id=topic_id)
        except Exception as error:
            logger.warning(f"Support: topic op {op.__name__} failed on {topic_id}: {error}")
