from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.text import Format

from src.telegram.states import MainMenu, Onboarding
from src.telegram.widgets import I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Group, Row, Start, SwitchTo, Url

from .getters import PLATFORMS, onboarding_getter
from .handlers import (
    on_change_location,
    on_dialog_start,
    on_platform_select,
    on_understood,
    on_works,
)

# O0 — entry
entry = Window(
    I18nFormat("msg-onboarding-entry"),
    SwitchTo(
        text=I18nFormat("btn-onboarding.connect"),
        id="onb_connect",
        state=Onboarding.PLATFORM,
    ),
    IgnoreUpdate(),
    state=Onboarding.ENTRY,
)

# O1 — device choice
_platform_buttons = Group(
    *(
        Button(
            text=I18nFormat(f"btn-onboarding.platform-{code}"),
            id=f"onb_plat_{code}",
            on_click=on_platform_select,
        )
        for code in PLATFORMS
    ),
    width=2,
)

platform = Window(
    I18nFormat("msg-onboarding-platform"),
    _platform_buttons,
    IgnoreUpdate(),
    state=Onboarding.PLATFORM,
)

# O2 — the 3-step setup (store link, deeplink and copyable live in the text)
setup = Window(
    I18nFormat("msg-onboarding-setup"),
    Row(
        Button(
            text=I18nFormat("btn-onboarding.works"),
            id="onb_works",
            on_click=on_works,
        ),
        SwitchTo(
            text=I18nFormat("btn-onboarding.fail"),
            id="onb_fail",
            state=Onboarding.HELP,
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.SETUP,
    getter=onboarding_getter,
)

# O3 — manual-refresh tip
refresh_tip = Window(
    I18nFormat("msg-onboarding-refresh-tip"),
    Button(
        text=I18nFormat("btn-onboarding.understood"),
        id="onb_understood",
        on_click=on_understood,
    ),
    IgnoreUpdate(),
    state=Onboarding.REFRESH_TIP,
    getter=onboarding_getter,
)

# O4 — success
success = Window(
    I18nFormat("msg-onboarding-success"),
    Start(
        text=I18nFormat("btn-onboarding.open-menu"),
        id="onb_open_menu",
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
    ),
    IgnoreUpdate(),
    state=Onboarding.SUCCESS,
)

# "Не получается" — self-service branch
help_window = Window(
    I18nFormat("msg-onboarding-help"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-onboarding.refresh-happ"),
            id="onb_refresh_happ",
            state=Onboarding.REFRESH_HAPP,
        ),
        Button(
            text=I18nFormat("btn-onboarding.change-location"),
            id="onb_change_location",
            on_click=on_change_location,
        ),
    ),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.support"),
            url=Format("{support_url}"),
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.HELP,
    getter=onboarding_getter,
)

# Manual config refresh screen (from the "Обновить в Happ" button)
refresh_happ = Window(
    I18nFormat("msg-onboarding-refresh-happ"),
    Start(
        text=I18nFormat("btn-onboarding.back-menu"),
        id="onb_refresh_back",
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
    ),
    IgnoreUpdate(),
    state=Onboarding.REFRESH_HAPP,
    getter=onboarding_getter,
)

router = Dialog(
    entry,
    platform,
    setup,
    refresh_tip,
    success,
    help_window,
    refresh_happ,
    on_start=on_dialog_start,
)
