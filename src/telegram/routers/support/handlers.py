from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from dishka import FromDishka
from loguru import logger

from src.application.common import BotService, SupportService
from src.application.dto import TelegramUserDto
from src.core.config import AppConfig
from src.core.constants import SUPPORT_CB_CLOSE, TARGET_USER_ID
from src.core.enums import Deeplink
from src.core.exceptions import SupportUnavailableError
from src.infrastructure.database.models.support import CHANNEL_TELEGRAM
from src.telegram.states import DashboardUser, Support

router = Router(name=__name__)

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
_CARD_NO_ACCESS_TEXT = "🚫 Карточка пользователя доступна только администраторам."


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


# ?start=usercard_<id> deep link — the operator's "🗂 Карточка" button (posted in the
# support topic) opens the full admin user dialog here, in the operator's own private
# chat, since an aiogram-dialog card cannot run inside a shared group topic. Same idiom
# as the other start-deeplinks in routers/extra/goto.py.
@router.message(
    F.chat.type == ChatType.PRIVATE,
    CommandStart(deep_link=True, ignore_case=True),
    F.text.contains(Deeplink.USERCARD),
)
async def on_user_card_entry(
    message: Message,
    command: CommandObject,
    user: TelegramUserDto,
    dialog_manager: DialogManager,
) -> None:
    args = command.args or ""
    prefix = Deeplink.USERCARD.with_underscore
    raw_id = args.removeprefix(prefix) if args.startswith(prefix) else ""
    if not raw_id.isdigit():
        logger.warning(f"{user.log} Bad usercard deep link args '{args}'")
        return
    # Gate on admin (role >= ADMIN) — the same bar as the dialog's USER_EDITOR permission.
    if not user.is_privileged:
        logger.warning(f"{user.log} Non-admin usercard deep link attempt for '{raw_id}'")
        await message.answer(_CARD_NO_ACCESS_TEXT)
        return

    target_user_id = int(raw_id)
    logger.info(f"{user.log} Opening admin card for user '{target_user_id}' via support")
    await dialog_manager.bg(
        user_id=user.telegram_id,
        chat_id=user.telegram_id,
    ).start(
        state=DashboardUser.MAIN,
        data={TARGET_USER_ID: target_user_id},
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


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
    # No message content in the log (privacy) — just enough to trace routing.
    logger.debug(
        f"Support: operator group msg chat_id={message.chat.id} thread_id={thread_id} "
        f"is_topic={message.is_topic_message} "
        f"from={message.from_user.id if message.from_user else None}"
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
        # Operator commands inside the topic (/close, /card; also /cmd@botname).
        await _handle_operator_command(
            stripped.split()[0].split("@")[0], thread_id, message, support
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


async def _handle_operator_command(
    command: str, thread_id: int, message: Message, support: SupportService
) -> None:
    if command == "/close":
        if await support.close_by_topic(thread_id):
            await message.answer(
                "✅ Диалог закрыт. Новое сообщение пользователя откроет его снова."
            )
    elif command == "/card":
        if not await support.post_card(thread_id):
            await message.answer("Карточка недоступна.")


# --- operator inline buttons on the topic header -----------------------------


def _support_callback_target(
    callback: CallbackQuery, config: AppConfig
) -> Optional[tuple[Message, int]]:
    """The (topic message, topic id) of a valid operator-group callback, else None."""
    message = callback.message
    if not config.support.is_active or not isinstance(message, Message):
        return None
    if message.chat.id != config.support.group_id or message.message_thread_id is None:
        return None
    return message, message.message_thread_id


@router.callback_query(F.data == SUPPORT_CB_CLOSE)
async def on_support_close_button(
    callback: CallbackQuery,
    config: FromDishka[AppConfig],
    support: FromDishka[SupportService],
) -> None:
    target = _support_callback_target(callback, config)
    if target is None:
        await callback.answer()
        return
    closed = await support.close_by_topic(target[1])
    await callback.answer("Диалог закрыт" if closed else "Диалог не найден")
