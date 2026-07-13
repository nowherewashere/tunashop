import html
import json
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from redis.asyncio import Redis

from src.application.common import BotService, Notifier, SupportService
from src.application.common.dao import (
    ReferralDao,
    SubscriptionDao,
    SupportDao,
    TransactionDao,
    UserDao,
)
from src.application.common.support import (
    build_message_event,
    build_status_event,
    support_events_channel,
)
from src.application.common.uow import UnitOfWork
from src.application.dto import (
    MessagePayloadDto,
    SupportConversationDto,
    SupportMessageDto,
    UserDto,
)
from src.core.config import AppConfig
from src.core.constants import (
    SUPPORT_CB_CLOSE,
    SUPPORT_CB_DEVICES,
    UNLIMITED_EXPIRE_YEAR,
)
from src.core.enums import Role, TransactionStatus
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
    author_for_sender,
)

# Telegram forum-topic name hard limit.
_TOPIC_NAME_MAX = 128

# Role → RU label, mirroring the admin card's `role` fluent (utils.ftl). The card is a
# hand-built HTML message (no DialogManager/translator here), so labels live inline.
_ROLE_LABELS_RU: dict[Role, str] = {
    Role.OWNER: "Владелец",
    Role.DEV: "Разработчик",
    Role.ADMIN: "Администратор",
    Role.PREVIEW: "Наблюдатель",
    Role.USER: "Пользователь",
    Role.SYSTEM: "Система",
}


def _fmt_traffic_limit(gb: int) -> str:
    # Matches i18n_format_traffic_limit semantics (0 = unlimited), in GB.
    return "∞" if not gb else f"{gb} ГБ"


def _fmt_device_limit(count: int) -> str:
    # Matches i18n_format_device_limit semantics (0 = unlimited).
    return "∞" if not count else str(count)


def _fmt_remaining(expire_at: datetime) -> str:
    # Compact "осталось" mirroring i18n_format_expire_time (unlimited/expired/д·ч·мин).
    if expire_at.year == UNLIMITED_EXPIRE_YEAR:
        return "∞"
    delta = expire_at - datetime_now()
    if delta.total_seconds() <= 0:
        return "истекла"
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} д" + (f" {hours} ч" if hours else "")
    if hours:
        return f"{hours} ч" + (f" {minutes} мин" if minutes else "")
    return f"{minutes} мин"


class SupportServiceImpl(SupportService):
    """Bridges site/bot users and operators through Telegram forum topics.

    The DB is the source of truth (the site reads it); the operator supergroup's
    topics are the live operator interface. One conversation (= one topic) per user
    carries both channels.
    """

    def __init__(
        self,
        bot: Bot,
        bot_service: BotService,
        notifier: Notifier,
        uow: UnitOfWork,
        support_dao: SupportDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        transaction_dao: TransactionDao,
        referral_dao: ReferralDao,
        config: AppConfig,
        redis: Redis,
    ) -> None:
        self.bot = bot
        # BotService builds the operator's "🗂 Карточка" deep link (resolves the bot
        # username the same way get_support_url does).
        self.bot_service = bot_service
        self.notifier = notifier
        self.uow = uow
        self.support_dao = support_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.transaction_dao = transaction_dao
        self.referral_dao = referral_dao
        self.config = config
        # Live push: operator replies + status changes are announced on a per-user
        # channel that the site's SSE endpoint subscribes to (see support_events_channel).
        self.redis = redis

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

        if reopened:
            if conv.telegram_topic_id is not None:
                # The operator had closed the topic; a new message reopens the same
                # thread so history stays in one place, and a fresh user card is posted
                # so the operator sees the current state at the start of every session.
                await self._safe_topic_op(
                    self.bot.reopen_forum_topic, conv.telegram_topic_id
                )
                await self._post_header(conv.telegram_topic_id, user)
            # Mirror the reopen to any open cabinet tab so its "closed" banner clears
            # live (the tab that sent already knows; this keeps other tabs in sync).
            await self._publish(user.id, build_status_event(CONVERSATION_OPEN))

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
            message = await self.support_dao.add_message(
                conv.id,
                direction=DIRECTION_OUTBOUND,
                sender=SENDER_OPERATOR,
                text=text,
                source=CHANNEL_TELEGRAM,
                operator_user_id=operator.id if operator else None,
                telegram_message_id=telegram_message_id,
            )
            await self.uow.commit()

        # Push the stored reply to the site in real time (the SSE stream forwards it),
        # so an open cabinet updates instantly instead of waiting for the next poll.
        await self._publish(
            conv.user_id,
            build_message_event(
                id=message.id,
                author=author_for_sender(message.sender),
                text=message.text,
                created_at=message.created_at.isoformat() if message.created_at else "",
            ),
        )

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
        await self._publish(conv.user_id, build_status_event(CONVERSATION_CLOSED))
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
            await self._publish(conv.user_id, build_status_event(CONVERSATION_CLOSED))
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
        # A closed conversation presents as a fresh chat on the initial load (after_id
        # == 0): the site then renders a clean new conversation (its static greeting),
        # not the previous, closed session's history — mirroring "no conversation yet".
        # The next user message reopens the same thread server-side
        # (ingest_from_user), and live polling (after_id > 0) still streams the open
        # conversation, so an operator closing it mid-session is reflected normally.
        # The DB keeps every message; this only shapes what the initial load renders.
        if after_id == 0 and conv.status == CONVERSATION_CLOSED:
            return None, []
        messages = await self.support_dao.list_messages(conv.id, after_id=after_id)
        return conv, messages

    # --- internals ---------------------------------------------------------

    async def _publish(self, user_id: int, event: dict[str, Any]) -> None:
        """Best-effort real-time fan-out to the user's SSE stream.

        A pub/sub failure must never break the operator flow: the message/status is
        already persisted, the site keeps its polling fallback, so we only log.
        """
        try:
            await self.redis.publish(support_events_channel(user_id), json.dumps(event))
        except Exception as error:
            logger.warning(f"Support: failed to publish event for user {user_id}: {error}")

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
        # Mirrors the admin user card (msg-user-main + msg-user-statistics): identity,
        # profile (role/language/registration/discounts), "invited by", subscription
        # details and recent payments — assembled as HTML since a DialogManager/translator
        # is not available here (the card is a hand-built message).
        lines = [f"🎫 <b>{html.escape(user.name)}</b> · <code>#{user.id}</code>"]
        if user.username:
            lines.append(f"Telegram: @{html.escape(user.username)}")
        elif user.telegram_id is not None:
            lines.append(f"Telegram ID: <code>{user.telegram_id}</code>")
        if user.email:
            lines.append(f"Email: {html.escape(user.email)}")
        lines.append("————")
        lines.append(self._render_profile(user))
        referrer_line = await self._render_referrer(user.id)
        if referrer_line:
            lines.append(referrer_line)
        lines.append("————")
        lines.append(await self._render_subscription(user.id))
        lines.append(await self._render_payments(user.id))

        # A failed username lookup must not drop the card: fall back to the two-button
        # keyboard (без «🗂 Карточка») rather than losing the whole header.
        try:
            card_url: Optional[str] = await self.bot_service.get_user_card_url(user.id)
        except Exception as error:
            logger.warning(f"Support: failed to build user-card deep link for {user.id}: {error}")
            card_url = None

        try:
            await self.bot.send_message(
                chat_id=self._group_id,
                message_thread_id=topic_id,
                text="\n".join(lines),
                reply_markup=self._operator_keyboard(card_url),
                disable_web_page_preview=True,
            )
        except Exception as error:
            logger.warning(f"Support: failed to post topic header for user {user.id}: {error}")

    @staticmethod
    def _operator_keyboard(card_url: Optional[str] = None) -> InlineKeyboardMarkup:
        rows = [
            [
                InlineKeyboardButton(text="🖥 Устройства", callback_data=SUPPORT_CB_DEVICES),
                InlineKeyboardButton(text="🔒 Закрыть", callback_data=SUPPORT_CB_CLOSE),
            ]
        ]
        # "🗂 Карточка" is a start deep link that opens the full admin user dialog in the
        # operator's private chat (an aiogram-dialog card cannot run inside a group topic).
        if card_url:
            rows.append([InlineKeyboardButton(text="🗂 Карточка", url=card_url)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _render_profile(self, user: UserDto) -> str:
        role_label = _ROLE_LABELS_RU.get(user.role, str(user.role))
        lines = [
            f"👤 Роль: {role_label} · Язык: {user.language.value.upper()}",
            f"💸 Скидки: персональная {user.personal_discount}% · "
            f"на покупку {user.purchase_discount}%",
        ]
        if user.created_at is not None:
            lines.append(f"📅 Регистрация: {user.created_at:%d.%m.%Y}")
        return "\n".join(lines)

    async def _render_referrer(self, user_id: int) -> Optional[str]:
        referral = await self.referral_dao.get_by_referred_id(user_id)
        if referral is None:
            return None
        referrer = referral.referrer
        if referrer.username:
            who = f"@{html.escape(referrer.username)}"
        elif referrer.telegram_id is not None:
            who = f"<code>{referrer.telegram_id}</code>"
        elif referrer.email:
            who = html.escape(referrer.email)
        else:
            who = f"#{referrer.id}"
        return f"👥 Пригласил: {who} · <code>#{referrer.id}</code>"

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
        return "\n".join(
            [
                f"💳 <b>{plan}</b> · {state} · до {subscription.expire_at:%d.%m.%Y}",
                f" • Трафик: {_fmt_traffic_limit(subscription.traffic_limit)}",
                f" • Устройства: {_fmt_device_limit(subscription.device_limit)}",
                f" • Осталось: {_fmt_remaining(subscription.expire_at)}",
            ]
        )

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
