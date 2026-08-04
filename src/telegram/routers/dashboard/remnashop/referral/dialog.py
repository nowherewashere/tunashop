from aiogram_dialog import Dialog, Window

from src.core.enums import BannerName
from src.telegram.keyboards import main_menu_button
from src.telegram.states import DashboardRemnashop, RemnashopReferral
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Row, Start

from .getters import referral_getter
from .handlers import on_enable_toggle

referral = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-referral-main"),
    Row(
        Button(
            text=I18nFormat("btn-referral.active-toggle"),
            id="enable",
            on_click=on_enable_toggle,
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=RemnashopReferral.MAIN,
    getter=referral_getter,
)

router = Dialog(referral)
