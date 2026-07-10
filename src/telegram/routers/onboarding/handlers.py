from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.kbd import Button

from src.application.common import EventPublisher, TranslatorRunner
from src.application.common.dao import UserConnectionStateDao
from src.application.dto import TelegramUserDto
from src.application.use_cases.onboarding.commands import (
    CancelOnboardingNudges,
    CancelOnboardingNudgesDto,
    ScheduleOnboardingNudges,
    ScheduleOnboardingNudgesDto,
)
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.core.metrics import FunnelStep
from src.telegram.states import MainMenu, Onboarding

from .getters import is_tv_platform
from .metrics import emit_funnel_step

_PLATFORM_PREFIX = "platform_"


async def on_dialog_start(start_data: Any, manager: DialogManager) -> None:
    """Arm the pre-connect nudge chain when the funnel opens (idempotent per user).

    Only the real funnel entry (DEVICE_CHOICE) arms the chain. Opening straight at
    another screen — the menu Support button → NOT_WORKING, or a nudge's fail-goto —
    is not a fresh connect attempt, so it must not schedule pre-connect nudges.
    """
    context = manager.current_context()
    if context is None or context.state != Onboarding.DEVICE_CHOICE:
        return
    user: TelegramUserDto = manager.middleware_data[USER_KEY]
    if user.telegram_id is None:
        return
    container = manager.middleware_data[CONTAINER_KEY]
    schedule = await container.get(ScheduleOnboardingNudges)
    await schedule.system(ScheduleOnboardingNudgesDto(telegram_id=user.telegram_id))

    # Funnel top: the user opened the connect flow (spec §5 `start`).
    publisher = await container.get(EventPublisher)
    await emit_funnel_step(publisher, FunnelStep.START, telegram_id=user.telegram_id)


async def on_platform_selected(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    """Store the chosen platform and move on to the connect instructions.

    TV platforms set up via phone/web import, so they get a dedicated screen.
    """
    platform = (widget.widget_id or "").removeprefix(_PLATFORM_PREFIX)
    dialog_manager.dialog_data["platform"] = platform

    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    container = dialog_manager.middleware_data[CONTAINER_KEY]
    publisher = await container.get(EventPublisher)
    await emit_funnel_step(
        publisher, FunnelStep.DEVICE_SELECTED, telegram_id=user.telegram_id, platform=platform
    )

    target = Onboarding.TV_CONNECT if is_tv_platform(platform) else Onboarding.CONNECT
    await dialog_manager.switch_to(target)


async def on_works(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    """User confirmed the connection works → show the refresh tip.

    Guard (spec fix #18): if the user has never actually connected — the same
    ``connected_once`` signal the hub uses for its primary-button switch — don't
    advance; pop a branded alert nudging them to finish connecting first.
    """
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    container = dialog_manager.middleware_data[CONTAINER_KEY]

    if user.telegram_id is not None:
        conn_state_dao = await container.get(UserConnectionStateDao)
        if not await conn_state_dao.is_connected_once(user.telegram_id):
            i18n = await container.get(TranslatorRunner)
            await callback.answer(
                text=i18n.get("onboarding-not-connected-yet"), show_alert=True
            )
            return

    await dialog_manager.switch_to(Onboarding.TIPS)


async def on_tips_ok(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    """Terminal step (there is no separate success screen): finishing the tip is
    the completion signal — stop any pending nudges and return to the main menu.
    """
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    if user.telegram_id is not None:
        container = dialog_manager.middleware_data[CONTAINER_KEY]
        cancel = await container.get(CancelOnboardingNudges)
        await cancel.system(CancelOnboardingNudgesDto(telegram_id=user.telegram_id))
    await dialog_manager.start(MainMenu.MAIN, mode=StartMode.RESET_STACK)
