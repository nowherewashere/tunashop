from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from dishka import FromDishka
from loguru import logger

from src.application.common import BotService, SupportService
from src.application.dto import TelegramUserDto
from src.core.config import AppConfig
from src.core.exceptions import SupportUnavailableError
from src.infrastructure.database.models.support import CHANNEL_TELEGRAM
from src.telegram.states import Support

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


@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.message_thread_id,
    Command("close"),
)
async def on_operator_close(
    message: Message,
    config: FromDishka[AppConfig],
    support: FromDishka[SupportService],
) -> None:
    if not _is_operator_group(message, config) or message.message_thread_id is None:
        return
    if await support.close_by_topic(message.message_thread_id):
        await message.answer("✅ Диалог закрыт. Новое сообщение пользователя откроет его снова.")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.message_thread_id)
async def on_operator_reply(
    message: Message,
    config: FromDishka[AppConfig],
    support: FromDishka[SupportService],
) -> None:
    if not _is_operator_group(message, config) or message.message_thread_id is None:
        return
    if message.from_user is None:
        return
    text = message.text or message.caption
    if not text or text.startswith("/"):
        return
    delivered = await support.ingest_from_operator(
        message.message_thread_id,
        operator_telegram_id=message.from_user.id,
        text=text.strip(),
        telegram_message_id=message.message_id,
    )
    if not delivered:
        logger.debug(f"Support: reply in unmapped topic {message.message_thread_id}, ignored")
