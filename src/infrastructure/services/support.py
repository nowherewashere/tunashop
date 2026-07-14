import html
import json
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from aiogram import Bot
from aiogram.fsm.storage.base import BaseStorage, StorageKey
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
    SubscriptionDto,
    SupportConversationDto,
    SupportMessageDto,
    UserDto,
)
from src.application.use_cases.user.queries.profile import GetUserDevices
from src.core.config import AppConfig
from src.core.constants import SUPPORT_CB_CLOSE, SUPPORT_FSM_STATE, UNLIMITED_EXPIRE_YEAR
from src.core.enums import PurchaseType, Role, TransactionStatus
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

_PURCHASE_TYPE_RU: dict[PurchaseType, str] = {
    PurchaseType.NEW: "Покупка",
    PurchaseType.RENEW: "Продление",
    PurchaseType.CHANGE: "Изменение",
}


def _blockquote(rows: list[str]) -> str:
    # Telegram HTML quote block used as each card section's body.
    return "<blockquote>" + "\n".join(rows) + "</blockquote>"


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _fmt_traffic_limit(gb: int) -> str:
    # Matches i18n_format_traffic_limit semantics (0 = unlimited), in GB.
    return "∞" if not gb else f"{gb} ГБ"


def _fmt_device_limit(count: int) -> str:
    # Matches i18n_format_device_limit semantics (0 = unlimited).
    return "∞" if not count else str(count)


def _fmt_duration(days: int) -> str:
    # Purchased term, RU-pluralised, mirroring i18n_format_days bucketing (год/месяц/день).
    if days <= 0:
        return "∞"
    if days % 365 == 0:
        years = days // 365
        return f"{years} {_ru_plural(years, 'год', 'года', 'лет')}"
    if days % 30 == 0:
        months = days // 30
        return f"{months} {_ru_plural(months, 'месяц', 'месяца', 'месяцев')}"
    return f"{days} {_ru_plural(days, 'день', 'дня', 'дней')}"


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
        get_user_devices: GetUserDevices,
        config: AppConfig,
        redis: Redis,
        storage: BaseStorage,
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
        # Devices are rendered inline in the card (the old 🖥 button is gone); this
        # use case fetches them (a remnawave round-trip) run as the system actor.
        self.get_user_devices = get_user_devices
        self.config = config
        # Live push: operator replies + status changes are announced on a per-user
        # channel that the site's SSE endpoint subscribes to (see support_events_channel).
        self.redis = redis
        # The dispatcher's aiogram FSM storage (shared instance), so an operator /close can
        # drop the client's in-bot Support.CHAT state (see _clear_bot_fsm).
        self.storage = storage

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
            # The forum topic is never Telegram-closed anymore (only the DB status
            # toggles), so there is nothing to reopen, and we do NOT re-post the user
            # card — that close→reopen→fresh-card churn was the bulk of the operator-topic
            # flood. The topic keeps its original header; operators refresh context on
            # demand with /card, and the user's message below just lands in the (quiet)
            # topic. Mirror the reopen to any open cabinet tab so its "closed" banner
            # clears live (the tab that sent already knows; this keeps other tabs in sync).
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
        # We no longer Telegram-close the forum topic (the close→reopen churn flooded the
        # group). The closed state lives in the DB + the published status event; a short
        # note keeps the operator's "handled" signal in the thread.
        await self._post_topic_note(topic_id, "🔒 Диалог закрыт оператором.")
        await self._publish(conv.user_id, build_status_event(CONVERSATION_CLOSED))
        await self._notify_telegram_close(conv, auto=False)
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
            # No Telegram topic-close (that was the flood, and a bulk run would also risk
            # per-group flood limits); the DB status + status event carry the close, and a
            # bot-channel user is told directly via DM below. No per-topic note here on the
            # bulk path to keep the group quiet — the topic simply goes idle.
            await self._publish(conv.user_id, build_status_event(CONVERSATION_CLOSED))
            await self._notify_telegram_close(conv, auto=True)
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
        # A CLOSED conversation still returns its full history + status on the initial load
        # (after_id == 0): the site renders the past messages plus the "закрыт — напишите,
        # чтобы продолжить" banner, and the next user message reopens the same thread
        # (ingest_from_user). (Previously a closed convo was presented as a fresh empty
        # chat, which lost the history until the user re-sent and reloaded.)
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

    async def _post_topic_note(self, topic_id: int, text: str) -> None:
        """A short operator-facing status line inside a topic (best-effort)."""
        try:
            await self.bot.send_message(
                chat_id=self._group_id,
                message_thread_id=topic_id,
                text=text,
                disable_web_page_preview=True,
            )
        except Exception as error:
            logger.warning(f"Support: failed to post topic note to {topic_id}: {error}")

    async def _notify_telegram_close(
        self, conv: SupportConversationDto, *, auto: bool
    ) -> None:
        """Tell a bot-channel client their support chat closed, mirroring the site banner.

        Operator ``/close`` (``auto=False``) is a HARD close: we also drop the client's
        ``Support.CHAT`` FSM so they truly leave the chat and must ``/support`` to reopen.
        Idle auto-close (``auto=True``) is SOFT: the FSM is left intact, so a new message
        reopens the same thread. Best-effort; only for users who last wrote from the bot."""
        if conv.last_user_channel != CHANNEL_TELEGRAM:
            return
        target = await self.user_dao.get_by_id(conv.user_id)
        if target is None or target.telegram_id is None:
            return
        if auto:
            text = (
                "🔒 Чат поддержки закрыт из-за неактивности. "
                "Напишите сюда снова или /support, чтобы продолжить."
            )
        else:
            await self._clear_bot_fsm(target.telegram_id)
            text = (
                "🔒 Оператор закрыл чат поддержки. "
                "Нажмите /support, чтобы открыть его снова."
            )
        try:
            await self.bot.send_message(chat_id=target.telegram_id, text=text)
        except Exception as error:
            logger.warning(
                f"Support: failed to notify user {conv.user_id} of close: {error}"
            )

    async def _clear_bot_fsm(self, telegram_id: int) -> None:
        """Drop the client's in-bot support FSM so an operator /close truly ends the chat.

        Guarded on the current state being ``Support.CHAT`` so an unrelated flow (e.g. a
        purchase) is never wiped. Private chat ⇒ chat_id == user_id == telegram_id, matching
        the key aiogram's FSMContext used to set the state (same shared storage instance)."""
        key = StorageKey(bot_id=self.bot.id, chat_id=telegram_id, user_id=telegram_id)
        try:
            if await self.storage.get_state(key) == SUPPORT_FSM_STATE:
                await self.storage.set_state(key, None)
        except Exception as error:
            logger.warning(f"Support: failed to clear FSM for tg {telegram_id}: {error}")

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
        # Operator-facing card mirroring the admin user screen: an identity header, then
        # bold section titles with <blockquote> bodies (Информация / Подписка /
        # Устройства / Платежи). Assembled as HTML — no DialogManager/translator here.
        lines = [f"🎫 <b>{html.escape(user.name)}</b> · <code>{user.id}</code>"]
        if user.username:
            lines.append(f"@{html.escape(user.username)}")
        elif user.telegram_id is not None:
            lines.append(f"<code>{user.telegram_id}</code>")
        if user.email:
            lines.append(html.escape(user.email))

        lines.append("")
        lines.append(self._render_profile_section(user, await self._render_referrer(user.id)))

        subscription = await self.subscription_dao.get_current(user.id)
        lines.append("")
        lines.append(self._render_subscription_section(subscription))

        devices_section = await self._render_devices_section(user.id, subscription)
        if devices_section:
            lines.append("")
            lines.append(devices_section)

        lines.append("")
        lines.append(await self._render_payments_section(user.id))

        # A failed username lookup must not drop the card: fall back to a keyboard with
        # only «🔒 Закрыть» rather than losing the whole header.
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
        # One row: «🗂 Карточка» (start deep link that opens the full admin user dialog
        # in the operator's private chat — a dialog card cannot run inside a group topic)
        # + «🔒 Закрыть». Devices are shown inline in the card now, so there is no 🖥
        # button. If the username can't be resolved yet, only «🔒 Закрыть» is shown.
        row = []
        if card_url:
            row.append(InlineKeyboardButton(text="🗂 Карточка", url=card_url))
        row.append(InlineKeyboardButton(text="🔒 Закрыть", callback_data=SUPPORT_CB_CLOSE))
        return InlineKeyboardMarkup(inline_keyboard=[row])

    def _render_profile_section(self, user: UserDto, referrer_line: Optional[str]) -> str:
        role_label = _ROLE_LABELS_RU.get(user.role, str(user.role))
        body = [
            f"👤 Роль: {role_label} · Язык: {user.language.value.upper()}",
            f"💸 Скидки: персональная {user.personal_discount}% · "
            f"на покупку {user.purchase_discount}%",
        ]
        if user.created_at is not None:
            body.append(f"📅 Регистрация: {user.created_at:%d.%m.%Y}")
        if referrer_line:
            body.append(referrer_line)
        return "📋 <b>Информация</b>\n" + _blockquote(body)

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

    def _render_subscription_section(self, subscription: Optional[SubscriptionDto]) -> str:
        if subscription is None:
            return "💳 <b>Подписка</b> · нет"
        plan = html.escape(subscription.plan_snapshot.name or "—")
        # State is conveyed by «Осталось» (истекла / ∞); the device LIMIT lives in the
        # devices section below (as current/limit), so neither is repeated here.
        body = [
            f" • Трафик: {_fmt_traffic_limit(subscription.traffic_limit)}",
            f" • Осталось: {_fmt_remaining(subscription.expire_at)}",
        ]
        return f"💳 <b>Подписка · {plan}</b>\n" + _blockquote(body)

    async def _render_devices_section(
        self, user_id: int, subscription: Optional[SubscriptionDto]
    ) -> Optional[str]:
        # Shown inline in the card (the 🖥 button is gone). Needs a remnawave round-trip,
        # so it is best-effort: any failure degrades to «н/д», never drops the card.
        if subscription is None:
            return None
        try:
            result = await self.get_user_devices.system(user_id)
        except Exception as error:
            logger.warning(f"Support: failed to load devices for user {user_id}: {error}")
            return "📱 <b>Устройства</b> · н/д"
        header = (
            f"📱 <b>Устройства · {result.current_count} / "
            f"{_fmt_device_limit(result.max_count)}</b>"
        )
        body = [
            f" • {html.escape(str(device.device_model or device.platform or 'устройство'))}"
            for device in result.devices[:10]
        ]
        if not body:
            body.append(" • нет активных")
        return header + "\n" + _blockquote(body)

    async def _render_payments_section(self, user_id: int) -> str:
        transactions = await self.transaction_dao.get_by_user(user_id)
        completed = [t for t in transactions if t.status == TransactionStatus.COMPLETED]
        completed.sort(key=lambda t: t.created_at or datetime_now(), reverse=True)
        if not completed:
            return "💰 <b>Платежи</b> · нет"
        body = []
        for t in completed[:3]:
            when = f"{t.created_at:%d.%m.%y}" if t.created_at else "—"
            at_time = f"{t.created_at:%H:%M}" if t.created_at else "—"
            ptype = _PURCHASE_TYPE_RU.get(t.purchase_type, str(t.purchase_type))
            plan = html.escape(t.plan_snapshot.name or "—")
            term = _fmt_duration(t.plan_snapshot.duration)
            amount = f"{t.pricing.final_amount:.0f} {t.currency.symbol}"
            body.append(f" • {when} · {at_time} · {ptype} {plan} на {term} · {amount}")
        return "💰 <b>Платежи</b>\n" + _blockquote(body)

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
