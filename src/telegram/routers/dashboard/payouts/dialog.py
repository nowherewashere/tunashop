from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.states import Dashboard, DashboardPayouts
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import (
    Button,
    Row,
    ScrollingGroup,
    Select,
    Start,
    SwitchTo,
)

from .getters import payout_detail_getter, payout_queue_getter
from .handlers import (
    on_payout_paid_prompt,
    on_payout_reject_prompt,
    on_payout_select,
    on_payout_start,
    on_reject_reason_input,
    on_tx_hash_input,
)

payouts = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-payouts-main"),
    ScrollingGroup(
        Select(
            text=Format("{item[label]}"),
            id="payout_select",
            item_id_getter=lambda item: item["id"],
            items="payout_items",
            type_factory=int,
            on_click=on_payout_select,
        ),
        id="scroll",
        width=1,
        height=8,
        hide_on_single_page=True,
        when=F["has_items"],
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPayouts.MAIN,
    getter=payout_queue_getter,
)

detail = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-payouts-detail"),
    Row(
        Button(
            text=I18nFormat("btn-payouts.start"),
            id="start",
            on_click=on_payout_start,
            when=F["is_requested"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-payouts.paid"),
            id="paid",
            on_click=on_payout_paid_prompt,
            when=F["is_open"],
        ),
        Button(
            text=I18nFormat("btn-payouts.reject"),
            id="reject",
            on_click=on_payout_reject_prompt,
            when=F["is_open"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPayouts.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPayouts.DETAIL,
    getter=payout_detail_getter,
)

tx_hash = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-payouts-tx-hash"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPayouts.DETAIL,
        ),
    ),
    MessageInput(func=on_tx_hash_input),
    IgnoreUpdate(),
    state=DashboardPayouts.TX_HASH,
    getter=payout_detail_getter,
)

reject_reason = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-payouts-reject"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPayouts.DETAIL,
        ),
    ),
    MessageInput(func=on_reject_reason_input),
    IgnoreUpdate(),
    state=DashboardPayouts.REJECT_REASON,
    getter=payout_detail_getter,
)

router = Dialog(payouts, detail, tx_hash, reject_reason)
