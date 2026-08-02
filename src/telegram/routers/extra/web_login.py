from typing import Any, Union

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from dishka import AsyncContainer, FromDishka
from dishka.integrations.aiogram import inject
from loguru import logger

from src.application.common.dao import BotLoginDao, PendingDeeplinkDao
from src.application.dto import TelegramUserDto
from src.application.use_cases.auth.commands.bot_login import (
    ResolveBotLogin,
    ResolveBotLoginDto,
)
from src.core.constants import CONTAINER_KEY, USER_KEY, WEB_LOGIN_CB_APPROVE, WEB_LOGIN_CB_DECLINE
from src.core.enums import Deeplink
from src.telegram.keyboards import CALLBACK_CHANNEL_CONFIRM, CALLBACK_RULES_ACCEPT
from src.telegram.states import MainMenu

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


async def _offer_confirmation(
    chat: Message,
    user: TelegramUserDto,
    token: str,
    bot_login_dao: BotLoginDao,
) -> bool:
    """Ask the person to confirm the sign-in. False when there is nothing left to ask.

    The request is checked before the buttons are offered: a two-minute token is very
    often already dead by the time someone gets here, and "ссылка устарела" beats a
    button that fails.
    """
    request = await bot_login_dao.get(token)
    if request is None or request.status != "pending":
        logger.info(f"{user.log} Web-login confirmation opened for a spent/expired token")
        await chat.answer(_EXPIRED_TEXT)
        return False

    logger.info(f"{user.log} Opened a website sign-in confirmation")
    await chat.answer(
        _CONFIRM_TEXT.format(origin=f" с адреса <code>{request.ip}</code>" if request.ip else ""),
        reply_markup=_confirm_keyboard(token),
    )
    return True


async def _open_main_menu(dialog_manager: DialogManager) -> None:
    await dialog_manager.start(
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


async def pending_web_login(
    callback: CallbackQuery, **data: Any
) -> Union[bool, dict[str, Any]]:
    """Claim a web-login deep link that a gate parked for this user.

    Used as the filter on the rules / channel confirmations: a first-time visitor
    arriving on the sign-in link meets those gates *before* the deep link is ever
    routed, so without this the login they came for is silently dropped and they land
    in the main menu instead. Returns the token to the handler when there is one, and
    stays out of the way (falling through to the menu's own handlers) when there is not.
    """
    user = data.get(USER_KEY)
    if not isinstance(user, TelegramUserDto) or user.telegram_id is None:
        return False

    container: AsyncContainer = data[CONTAINER_KEY]
    pending = await container.get(PendingDeeplinkDao)
    token = await pending.take(user.telegram_id, Deeplink.WEBLOGIN.with_underscore)
    if not token:
        return False

    return {"web_login_token": token}


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

    await _offer_confirmation(message, user, token, bot_login_dao)


@router.callback_query(F.data == CALLBACK_RULES_ACCEPT, pending_web_login)
@router.callback_query(F.data == CALLBACK_CHANNEL_CONFIRM, pending_web_login)
@inject
async def on_gate_passed(
    callback: CallbackQuery,
    user: TelegramUserDto,
    dialog_manager: DialogManager,
    web_login_token: str,
    bot_login_dao: FromDishka[BotLoginDao],
) -> None:
    """Resume the sign-in the rules / channel gate interrupted.

    Registered in this router, which is included before ``menu``, so a person who came
    for the website login gets the confirmation once they have met the requirement —
    the menu's own accept handler still runs for everyone else. The main menu follows
    the decision, not the requirement, so nobody is asked to confirm from inside it.
    """
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    logger.info(f"{user.log} Passed a gate with a web-login deep link waiting")
    if not await _offer_confirmation(callback.message, user, web_login_token, bot_login_dao):
        # The token died while they were reading the rules: there is nothing left to
        # confirm, so give them the product instead of an empty chat.
        await _open_main_menu(dialog_manager)

    await callback.answer()


@router.callback_query(F.data.startswith(WEB_LOGIN_CB_APPROVE))
@inject
async def on_web_login_approve(
    callback: CallbackQuery,
    user: TelegramUserDto,
    dialog_manager: DialogManager,
    resolve_bot_login: FromDishka[ResolveBotLogin],
) -> None:
    await _resolve(callback, user, dialog_manager, resolve_bot_login, approve=True)


@router.callback_query(F.data.startswith(WEB_LOGIN_CB_DECLINE))
@inject
async def on_web_login_decline(
    callback: CallbackQuery,
    user: TelegramUserDto,
    dialog_manager: DialogManager,
    resolve_bot_login: FromDishka[ResolveBotLogin],
) -> None:
    await _resolve(callback, user, dialog_manager, resolve_bot_login, approve=False)


async def _resolve(
    callback: CallbackQuery,
    user: TelegramUserDto,
    dialog_manager: DialogManager,
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

    # Only after they said "это я": someone who declined a sign-in they did not start
    # wants the incident closed, not a product menu. A declined-in-error user still has
    # /start. Never on the onboarding funnel — they came to sign in, and the site is
    # already carrying them through the install steps.
    if approve:
        await _open_main_menu(dialog_manager)

    await callback.answer()
