from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.states import MainMenu, Onboarding
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Group, Row, Start, SwitchTo, Url
from src.telegram.window import Window

from .getters import connect_getter, not_working_getter, tips_getter, tv_connect_getter
from .handlers import on_dialog_start, on_platform_selected, on_tips_ok, on_works

device_choice = Window(
    Banner(BannerName.ONBOARDING_DEVICE),
    I18nFormat("msg-onboarding-device"),
    Group(
        Button(
            text=I18nFormat("btn-onboarding.platform-ios"),
            id="platform_ios",
            on_click=on_platform_selected,
        ),
        Button(
            text=I18nFormat("btn-onboarding.platform-android"),
            id="platform_android",
            on_click=on_platform_selected,
        ),
        Button(
            text=I18nFormat("btn-onboarding.platform-windows"),
            id="platform_windows",
            on_click=on_platform_selected,
        ),
        Button(
            text=I18nFormat("btn-onboarding.platform-linux"),
            id="platform_linux",
            on_click=on_platform_selected,
        ),
        Button(
            text=I18nFormat("btn-onboarding.platform-appletv"),
            id="platform_apple_tv",
            on_click=on_platform_selected,
        ),
        Button(
            text=I18nFormat("btn-onboarding.platform-androidtv"),
            id="platform_android_tv",
            on_click=on_platform_selected,
        ),
        width=2,
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.menu-return"),
            id="back_main_menu",
            state=MainMenu.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.DEVICE_CHOICE,
)

connect = Window(
    Banner(BannerName.ONBOARDING_CONNECT),
    I18nFormat("msg-onboarding-connect"),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.store"),
            url=Format("{store_link}"),
            id="store_link",
            when=~F["is_apple"],
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.store-global"),
            url=Format("{store_link}"),
            id="store_global",
            when="is_apple",
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.store-ru"),
            url=Format("{store_link_ru}"),
            id="store_ru",
            when="is_apple",
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.open"),
            url=Format("{open_url}"),
            id="open_happ",
            when="has_open_url",
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-onboarding.works"),
            id="works",
            on_click=on_works,
            style=Style(ButtonStyle.SUCCESS),
        ),
        SwitchTo(
            text=I18nFormat("btn-onboarding.fail"),
            id="fail",
            state=Onboarding.NOT_WORKING,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back_device",
            state=Onboarding.DEVICE_CHOICE,
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.CONNECT,
    getter=connect_getter,
)

tv_connect = Window(
    Banner(BannerName.ONBOARDING_TV),
    I18nFormat("msg-onboarding-tv"),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.faq"),
            url=Format("{faq_url}"),
            id="tv_faq",
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Url(
            text=I18nFormat("btn-onboarding.web-import"),
            url=Format("{web_import_url}"),
            id="tv_web_import",
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-onboarding.works"),
            id="works",
            on_click=on_works,
            style=Style(ButtonStyle.SUCCESS),
        ),
        SwitchTo(
            text=I18nFormat("btn-onboarding.fail"),
            id="fail",
            state=Onboarding.NOT_WORKING,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back_device",
            state=Onboarding.DEVICE_CHOICE,
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.TV_CONNECT,
    getter=tv_connect_getter,
)

# Terminal screen: the former standalone "success" window was dropped, so this
# tip screen closes the funnel. It carries the success banner and its "Понятно"
# button both cancels pending nudges (our completion hook) and returns to the menu.
tips = Window(
    Banner(BannerName.ONBOARDING_SUCCESS),
    I18nFormat("msg-onboarding-tips"),
    Row(
        Button(
            text=I18nFormat("btn-onboarding.tips-ok"),
            id="tips_ok",
            on_click=on_tips_ok,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.TIPS,
    getter=tips_getter,
)

not_working = Window(
    Banner(BannerName.ONBOARDING_FAIL),
    I18nFormat("msg-onboarding-fail"),
    Row(
        Url(
            text=I18nFormat("btn-menu.support"),
            url=Format("{support_url}"),
            id="support",
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        # From the menu Support button: Back returns to the main menu.
        Start(
            text=I18nFormat("btn-back.menu-return"),
            id="nw_back_menu",
            state=MainMenu.MAIN,
            mode=StartMode.RESET_STACK,
            when="from_menu",
        ),
        # Inside the funnel: Back returns to the connect step to retry.
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="nw_back_connect",
            state=Onboarding.CONNECT,
            when=~F["from_menu"],
        ),
    ),
    IgnoreUpdate(),
    state=Onboarding.NOT_WORKING,
    getter=not_working_getter,
)

router = Dialog(
    device_choice,
    connect,
    tv_connect,
    tips,
    not_working,
    on_start=on_dialog_start,
)
