from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.dto import TelegramUserDto
from src.application.use_cases.settings.commands.referral import ToggleReferralSystem
from src.core.constants import USER_KEY


@inject
async def on_enable_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    toggle_referral_system: FromDishka[ToggleReferralSystem],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    await toggle_referral_system(user)
