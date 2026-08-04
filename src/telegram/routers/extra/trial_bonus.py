from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka import FromDishka
from dishka.integrations.aiogram import inject
from loguru import logger

from src.application.common import TranslatorRunner
from src.application.dto import TelegramUserDto
from src.application.use_cases.broadcast.commands.bonus import (
    ClaimTrialBonus,
    ClaimTrialBonusDto,
    TrialBonusOutcome,
)
from src.core.constants import DATETIME_VIEW_FORMAT, TRIAL_BONUS_CB
from src.core.enums import TrialBonusResult

router = Router(name=__name__)

_RESULT_KEYS = {
    TrialBonusResult.GRANTED: "ntf-trial-bonus.granted",
    TrialBonusResult.ALREADY_CLAIMED: "ntf-trial-bonus.already-claimed",
    TrialBonusResult.NOT_ELIGIBLE: "ntf-trial-bonus.not-eligible",
    TrialBonusResult.UNAVAILABLE: "ntf-trial-bonus.unavailable",
}


def _strip_bonus_button(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    rows = [
        [button for button in row if not (button.callback_data or "").startswith(TRIAL_BONUS_CB)]
        for row in markup.inline_keyboard
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


async def _retire_button(callback: CallbackQuery, user: TelegramUserDto) -> None:
    """Take the spent button off the broadcast message.

    Cosmetic only — pressing it again is already refused by the claim ledger — but a
    button that keeps offering a day nobody can get any more reads as broken.
    """
    message = callback.message
    if not isinstance(message, Message) or not message.reply_markup:
        return

    try:
        await message.edit_reply_markup(reply_markup=_strip_bonus_button(message.reply_markup))
    except Exception as e:  # noqa: BLE001 - message too old / already edited / identical
        logger.debug(f"{user.log} Could not drop the spent trial bonus button: {e}")


@router.callback_query(F.data.startswith(TRIAL_BONUS_CB))
@inject
async def on_trial_bonus(
    callback: CallbackQuery,
    user: TelegramUserDto,
    i18n: FromDishka[TranslatorRunner],
    claim_trial_bonus: FromDishka[ClaimTrialBonus],
) -> None:
    raw_task_id = (callback.data or "").removeprefix(TRIAL_BONUS_CB)

    try:
        task_id = UUID(raw_task_id)
    except ValueError:
        # A keyboard that never went through StartBroadcast (admin preview) still carries
        # the bare prefix, so there is no broadcast — and no claim — behind the press.
        logger.debug(f"{user.log} Pressed an unbound trial bonus button '{raw_task_id}'")
        await callback.answer(i18n.get(_RESULT_KEYS[TrialBonusResult.UNAVAILABLE]), show_alert=True)
        return

    outcome: TrialBonusOutcome = await claim_trial_bonus(user, ClaimTrialBonusDto(task_id))

    text = i18n.get(
        _RESULT_KEYS[outcome.result],
        days=outcome.days,
        expire_at=outcome.expire_at.strftime(DATETIME_VIEW_FORMAT) if outcome.expire_at else "",
    )
    await callback.answer(text, show_alert=True)

    if outcome.result in (TrialBonusResult.GRANTED, TrialBonusResult.ALREADY_CLAIMED):
        await _retire_button(callback, user)
