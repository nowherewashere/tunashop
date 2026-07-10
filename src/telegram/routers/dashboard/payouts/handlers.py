from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Notifier
from src.application.dto import MessagePayloadDto, TelegramUserDto
from src.application.use_cases.referral.commands.operator import (
    CompletePayout,
    CompletePayoutDto,
    PayoutActionDto,
    RejectPayout,
    RejectPayoutDto,
    StartPayout,
)
from src.core.constants import USER_KEY
from src.core.exceptions import ReferralError
from src.telegram.states import DashboardPayouts


def _payout_id(dialog_manager: DialogManager) -> int:
    return int(dialog_manager.dialog_data["payout_id"])


async def _notify_error(notifier: Notifier, user: TelegramUserDto, message: str) -> None:
    await notifier.notify_user(
        user=user,
        payload=MessagePayloadDto(i18n_key="raw-message", i18n_kwargs={"content": message}),
    )


async def on_payout_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    item_id: int,
) -> None:
    dialog_manager.dialog_data["payout_id"] = int(item_id)
    await dialog_manager.switch_to(state=DashboardPayouts.DETAIL)


@inject
async def on_payout_start(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    start_payout: FromDishka[StartPayout],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    try:
        await start_payout.system(
            PayoutActionDto(payout_id=_payout_id(dialog_manager), operator_id=user.telegram_id)
        )
    except ReferralError as e:
        await callback.answer(str(e), show_alert=True)
        return
    # Stay on the detail so the operator can mark it paid next.
    await dialog_manager.switch_to(state=DashboardPayouts.DETAIL)


async def on_payout_paid_prompt(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await dialog_manager.switch_to(state=DashboardPayouts.TX_HASH)


async def on_payout_reject_prompt(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await dialog_manager.switch_to(state=DashboardPayouts.REJECT_REASON)


@inject
async def on_tx_hash_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    complete_payout: FromDishka[CompletePayout],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    settlement_ref = (message.text or "").strip()
    if not settlement_ref:
        return

    try:
        await complete_payout.system(
            CompletePayoutDto(
                payout_id=_payout_id(dialog_manager),
                operator_id=user.telegram_id,
                settlement_ref=settlement_ref,
            )
        )
    except ReferralError as e:
        await _notify_error(notifier, user, str(e))
        return
    await dialog_manager.switch_to(state=DashboardPayouts.MAIN)


@inject
async def on_reject_reason_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    reject_payout: FromDishka[RejectPayout],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    reason = (message.text or "").strip()
    if not reason:
        return

    try:
        await reject_payout.system(
            RejectPayoutDto(
                payout_id=_payout_id(dialog_manager),
                operator_id=user.telegram_id,
                reason=reason,
            )
        )
    except ReferralError as e:
        await _notify_error(notifier, user, str(e))
        return
    await dialog_manager.switch_to(state=DashboardPayouts.MAIN)
