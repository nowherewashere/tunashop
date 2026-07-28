from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dishka import FromDishka
from dishka.integrations.aiogram import inject
from loguru import logger

from src.application.common.dao import BotLoginDao
from src.application.dto import TelegramUserDto
from src.application.use_cases.auth.commands.bot_login import (
    ResolveBotLogin,
    ResolveBotLoginDto,
)
from src.core.constants import WEB_LOGIN_CB_APPROVE, WEB_LOGIN_CB_DECLINE
from src.core.enums import Deeplink

router = Router(name=__name__)

_CONFIRM_TEXT = (
    "🔐 <b>Подтверждение входа на сайте</b>\n\n"
    "Запрос на вход в аккаунт Tuna{origin}.\n\n"
    "Подтверждайте, только если вы <b>прямо сейчас</b> сами открыли вход на сайте. "
    "Если вход начали не вы — нажмите «Это не я»."
)
_APPROVED_TEXT = "✅ Вход подтверждён. Возвращайтесь на сайт — он уже открывается."
_DECLINED_TEXT = "🚫 Вход отклонён. Ничего не произошло."
_EXPIRED_TEXT = "⌛ Ссылка устарела или уже использована. Начните вход на сайте заново."
_BAD_LINK_TEXT = "⚠️ Ссылка входа повреждена. Начните вход на сайте заново."


def _confirm_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Это я, войти", callback_data=f"{WEB_LOGIN_CB_APPROVE}{token}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Это не я", callback_data=f"{WEB_LOGIN_CB_DECLINE}{token}"
                )
            ],
        ]
    )


@router.message(
    F.chat.type == ChatType.PRIVATE,
    CommandStart(deep_link=True, ignore_case=True),
    F.text.contains(Deeplink.WEBLOGIN),
)
@inject
async def on_web_login(
    message: Message,
    command: CommandObject,
    user: TelegramUserDto,
    bot_login_dao: FromDishka[BotLoginDao],
) -> None:
    """Ask before honouring a sign-in started on the website.

    Deliberately NOT auto-approving. Opening a link is not consent: auto-approval
    would turn any "tap here" message into a working account takeover, since the
    attacker only has to get the victim to follow a link they generated. The
    confirmation — and the origin shown with it — are what make this safe.
    """
    args = command.args or ""
    prefix = Deeplink.WEBLOGIN.with_underscore
    token = args.removeprefix(prefix) if args.startswith(prefix) else ""
    if not token:
        logger.warning(f"{user.log} Bad web-login deep link args '{args}'")
        await message.answer(_BAD_LINK_TEXT)
        return

    # Check before offering the buttons: a two-minute token is very often already dead
    # by the time someone gets here, and "ссылка устарела" beats a button that fails.
    request = await bot_login_dao.get(token)
    if request is None or request.status != "pending":
        logger.info(f"{user.log} Web-login confirmation opened for a spent/expired token")
        await message.answer(_EXPIRED_TEXT)
        return

    logger.info(f"{user.log} Opened a website sign-in confirmation")
    await message.answer(
        _CONFIRM_TEXT.format(origin=f" с адреса <code>{request.ip}</code>" if request.ip else ""),
        reply_markup=_confirm_keyboard(token),
    )


@router.callback_query(F.data.startswith(WEB_LOGIN_CB_APPROVE))
@inject
async def on_web_login_approve(
    callback: CallbackQuery,
    user: TelegramUserDto,
    resolve_bot_login: FromDishka[ResolveBotLogin],
) -> None:
    await _resolve(callback, user, resolve_bot_login, approve=True)


@router.callback_query(F.data.startswith(WEB_LOGIN_CB_DECLINE))
@inject
async def on_web_login_decline(
    callback: CallbackQuery,
    user: TelegramUserDto,
    resolve_bot_login: FromDishka[ResolveBotLogin],
) -> None:
    await _resolve(callback, user, resolve_bot_login, approve=False)


async def _resolve(
    callback: CallbackQuery,
    user: TelegramUserDto,
    resolve_bot_login: ResolveBotLogin,
    approve: bool,
) -> None:
    prefix = WEB_LOGIN_CB_APPROVE if approve else WEB_LOGIN_CB_DECLINE
    token = (callback.data or "").removeprefix(prefix)

    # The actor is whoever pressed the button, so the session can only ever be issued
    # for this Telegram account — the website has no say in whose it gets.
    resolved = await resolve_bot_login(user, ResolveBotLoginDto(token=token, approve=approve))

    if not resolved:
        text = _EXPIRED_TEXT
    else:
        text = _APPROVED_TEXT if approve else _DECLINED_TEXT

    if isinstance(callback.message, Message):
        # Drop the buttons so the confirmation cannot be pressed twice.
        try:
            await callback.message.edit_text(text)
        except Exception as e:  # noqa: BLE001 - message too old / already edited
            logger.debug(f"{user.log} Could not edit web-login confirmation: {e}")
    await callback.answer()
