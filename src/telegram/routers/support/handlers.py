from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject
from dishka import FromDishka
from loguru import logger

from src.application.common import BotService, SupportService
from src.application.dto import TelegramUserDto
from src.core.config import AppConfig
from src.core.exceptions import SupportUnavailableError
from src.infrastructure.database.models.support import CHANNEL_TELEGRAM
from src.telegram.states import Support

router = Router(name=__name__)


class _SupportDiagMiddleware(BaseMiddleware):
    """TEMP diagnostic: log the chat of every message, then pass it through unchanged.

    Runs as an outer middleware on the (first-registered) support router, so it sees
    every message before handler resolution and never alters routing. Used to pin down
    where operators' replies actually arrive (private vs the support supergroup topic).
    Remove once support delivery is confirmed.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            logger.info(
                f"SUPPORT-DIAG chat.type={event.chat.type!r} chat.id={event.chat.id} "
                f"thread_id={event.message_thread_id} is_topic={event.is_topic_message} "
                f"from={event.from_user.id if event.from_user else None} "
                f"text={(event.text or event.caption)!r}"
            )
        return await handler(event, data)


router.message.outer_middleware(_SupportDiagMiddleware())

# ?start=support deep link — lets any "contact support" button funnel into the in-bot
# chat instead of the operator's private @username.
DEEPLINK_SUPPORT = "support"

_ENTER_TEXT = (
    "🛟 Вы на связи с поддержкой.\n\n"
    "Опишите проблему — оператор ответит здесь, в этом чате. "
    "Чтобы выйти, отправьте /stop."
)
_LEAVE_TEXT = "Вы вышли из чата поддержки. Отправьте /start, чтобы вернуться в меню."
_UNAVAILABLE_TEXT = "Поддержка сейчас недоступна, попробуйте позже."


# --- user side (private chat) ------------------------------------------------


@router.message(
    F.chat.type == ChatType.PRIVATE, CommandStart(magic=F.args == DEEPLINK_SUPPORT)
)
@router.message(F.chat.type == ChatType.PRIVATE, Command("support"))
async def on_support_entry(
    message: Message,
    user: TelegramUserDto,
    state: FSMContext,
    config: FromDishka[AppConfig],
    bot_service: FromDishka[BotService],
) -> None:
    if not config.support.is_active:
        await _send_fallback(message, bot_service)
        return
    await state.set_state(Support.CHAT)
    await message.answer(_ENTER_TEXT)


@router.message(StateFilter(Support.CHAT), Command("stop"))
async def on_support_stop(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_LEAVE_TEXT)


@router.message(StateFilter(Support.CHAT), F.text, ~F.text.startswith("/"))
async def on_support_user_message(
    message: Message,
    user: TelegramUserDto,
    support: FromDishka[SupportService],
) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    try:
        await support.ingest_from_user(user, text, CHANNEL_TELEGRAM)
    except SupportUnavailableError:
        await message.answer(_UNAVAILABLE_TEXT)


async def _send_fallback(message: Message, bot_service: BotService) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Написать в поддержку", url=bot_service.get_support_url())]
        ]
    )
    await message.answer("Поддержка на связи в Telegram.", reply_markup=keyboard)


# --- operator side (forum topics in the support supergroup) ------------------


def _is_operator_group(message: Message, config: AppConfig) -> bool:
    return config.support.is_active and message.chat.id == config.support.group_id


# One handler for every message in the operator group (string chat-type literals to
# avoid any enum/str set-membership subtlety). We resolve the topic INSIDE — matching
# on message_thread_id in the decorator silently dropped replies whose thread id was
# not populated, and left nothing in the log to see why.
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_operator_group_message(
    message: Message,
    config: FromDishka[AppConfig],
    support: FromDishka[SupportService],
) -> None:
    if not _is_operator_group(message, config):
        return

    thread_id = message.message_thread_id
    text = message.text or message.caption
    logger.info(
        f"Support: operator group msg chat_id={message.chat.id} thread_id={thread_id} "
        f"is_topic={message.is_topic_message} "
        f"from={message.from_user.id if message.from_user else None} text={text!r}"
    )

    if thread_id is None:
        # A message outside any topic (the group's General tab) can't be routed to a
        # user. Only nudge when the operator clearly tried to reply to a relayed message,
        # so normal General chatter isn't spammed.
        replied = message.reply_to_message
        if replied is not None and replied.from_user is not None and replied.from_user.is_bot:
            await message.answer(
                "⚠️ Отвечайте внутри темы пользователя — сообщения в General не доходят."
            )
        return

    if message.from_user is None or not text:
        return

    stripped = text.strip()
    if stripped.startswith("/"):
        # /close (and /close@botname) closes the conversation behind this topic.
        if stripped.split()[0].split("@")[0] == "/close":
            if await support.close_by_topic(thread_id):
                await message.answer(
                    "✅ Диалог закрыт. Новое сообщение пользователя откроет его снова."
                )
        return

    delivered = await support.ingest_from_operator(
        thread_id,
        operator_telegram_id=message.from_user.id,
        text=stripped,
        telegram_message_id=message.message_id,
    )
    if not delivered:
        logger.debug(f"Support: reply in unmapped topic {thread_id}, ignored")
