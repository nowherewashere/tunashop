from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button

from src.application.dto import TelegramUserDto
from src.application.use_cases.onboarding.commands import (
    CancelOnboardingNudges,
    CancelOnboardingNudgesDto,
    ScheduleOnboardingNudges,
    ScheduleOnboardingNudgesDto,
)
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.telegram.states import Onboarding

_PLATFORM_PREFIX = "onb_plat_"


async def on_dialog_start(start_data: Any, manager: DialogManager) -> None:
    """Arm the pre-connect nudge chain when the funnel opens (idempotent per user)."""
    user: TelegramUserDto = manager.middleware_data[USER_KEY]
    if user.telegram_id is None:
        return
    container = manager.middleware_data[CONTAINER_KEY]
    schedule = await container.get(ScheduleOnboardingNudges)
    await schedule.system(ScheduleOnboardingNudgesDto(telegram_id=user.telegram_id))


async def on_platform_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    platform = (widget.widget_id or "").removeprefix(_PLATFORM_PREFIX)
    dialog_manager.dialog_data["platform"] = platform
    await dialog_manager.switch_to(Onboarding.SETUP)


async def on_works(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await dialog_manager.switch_to(Onboarding.REFRESH_TIP)


async def on_understood(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    """Reaching success is the completion signal — stop any pending nudges."""
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    if user.telegram_id is not None:
        container = dialog_manager.middleware_data[CONTAINER_KEY]
        cancel = await container.get(CancelOnboardingNudges)
        await cancel.system(CancelOnboardingNudgesDto(telegram_id=user.telegram_id))
    await dialog_manager.switch_to(Onboarding.SUCCESS)
