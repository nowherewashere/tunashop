from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.keyboards import back_main_menu_button, connect_buttons
from src.telegram.states import Onboarding
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, CopyText, Group, Row, SwitchTo, Url

from .getters import PLATFORMS, onboarding_getter
from .handlers import on_dialog_start, on_platform_select, on_understood, on_works

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
    Banner(BannerName.SUBSCRIPTION),
    I18nFormat("msg-onboarding-platform"),
    _platform_buttons,
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Onboarding.PLATFORM,
    getter=onboarding_getter,
)

setup = Window(
    Banner(BannerName.SUBSCRIPTION),
    I18nFormat(
        "msg-onboarding-setup",
        platform=F["platform"],
        store_link=F["store_link"],
        import_url=F["import_url"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-onboarding.works"),
            id="onb_works",
            on_click=on_works,
            style=Style(ButtonStyle.SUCCESS),
        ),
        SwitchTo(
            text=I18nFormat("btn-onboarding.fail"),
            id="onb_fail",
            state=Onboarding.HELP,
        ),
    ),
    Row(
        CopyText(
            text=I18nFormat("btn-onboarding.copy"),
            copy_text=Format("{subscription_url}"),
            when=F["subscription_url"],
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Onboarding.SETUP,
    getter=onboarding_getter,
)

refresh_tip = Window(
    Banner(BannerName.SUBSCRIPTION),
    I18nFormat("msg-onboarding-refresh-tip"),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.refresh-video"),
            url=Format("{refresh_video_url}"),
            when=F["has_refresh_video"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-onboarding.understood"),
            id="onb_understood",
            on_click=on_understood,
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.REFRESH_TIP,
    getter=onboarding_getter,
)

success = Window(
    Banner(BannerName.SUBSCRIPTION),
    I18nFormat("msg-onboarding-success"),
    *connect_buttons,
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Onboarding.SUCCESS,
    getter=onboarding_getter,
)

help_window = Window(
    Banner(BannerName.SUBSCRIPTION),
    I18nFormat("msg-onboarding-help"),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.refresh-video"),
            url=Format("{refresh_video_url}"),
            when=F["has_refresh_video"],
        ),
    ),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.support"),
            url=Format("{support_url}"),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="onb_help_back",
            state=Onboarding.SETUP,
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Onboarding.HELP,
    getter=onboarding_getter,
)

router = Dialog(
    platform,
    setup,
    refresh_tip,
    success,
    help_window,
    on_start=on_dialog_start,
)
