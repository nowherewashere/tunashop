from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.application.common.policy import Permission
from src.core.constants import INLINE_QUERY_INVITE, PAYMENT_PREFIX
from src.core.enums import BannerName
from src.telegram.keyboards import build_buttons_row, connect_buttons, onboarding_connect_buttons
from src.telegram.routers.dashboard.handlers import on_smart_search
from src.telegram.states import Dashboard, MainMenu, Onboarding, Subscription
from src.telegram.utils import require_permission
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import (
    Button,
    Column,
    ListGroup,
    Row,
    Select,
    Start,
    SwitchInlineQueryChosenChatButton,
    SwitchTo,
)
from src.telegram.window import Window

from .getters import (
    device_confirm_delete_getter,
    devices_getter,
    invite_about_getter,
    invite_getter,
    invite_pay_getter,
    invite_withdraw_getter,
    invite_withdraw_method_getter,
    invite_withdraw_stars_getter,
    menu_getter,
)
from .handlers import (
    on_device_delete_all_confirm,
    on_device_delete_confirm,
    on_device_delete_request,
    on_get_trial,
    on_invite,
    on_invite_withdraw_click,
    on_pay_with_balance_select,
    on_reissue_subscription_confirm,
    on_reset_referral_code,
    on_show_qr,
    on_stars_withdraw_confirm,
    on_text_button_click,
    on_withdraw_method_crypto,
    on_withdraw_method_stars,
    on_withdraw_wallet_input,
    show_reason,
)

custom_buttons = (
    build_buttons_row(1, text_on_click=on_text_button_click),
    build_buttons_row(2, text_on_click=on_text_button_click),
    build_buttons_row(3, text_on_click=on_text_button_click),
)

menu = Window(
    Banner(BannerName.MENU),
    I18nFormat("msg-main-menu"),
    *connect_buttons,
    *onboarding_connect_buttons,
    # Trial-ending soft upsell (spec §7) — prominent when the trial has <4h left.
    Row(
        Start(
            text=I18nFormat("btn-menu.subscribe-standard"),
            id=f"{PAYMENT_PREFIX}subscribe_ending",
            state=Subscription.PLANS,
            data={"goto_buy": True},
            when=F["trial_ending"],
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu.connect-not-available"),
            id="not_available",
            on_click=show_reason,
        ),
        when=F["has_subscription"] & ~F["connectable"],
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu.trial"),
            id="trial_free",
            on_click=on_get_trial,
            when=F["trial_available"] & F["trial_is_free"],
            style=Style(ButtonStyle.SUCCESS),
        ),
        Button(
            text=I18nFormat("btn-menu.trial-paid"),
            id="trial_paid",
            on_click=on_get_trial,
            when=F["trial_available"] & ~F["trial_is_free"],
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-menu.devices"),
            id="devices",
            state=MainMenu.DEVICES,
            when=F["has_device_limit"],
        ),
        # New/trial users go straight into the buy flow (unambiguously a NEW
        # purchase) — the goto_buy start_data makes the dialog open at the plan
        # list and skip the MAIN chooser. Paid users keep MAIN, where they choose
        # between renew and change.
        Start(
            text=I18nFormat("btn-menu.subscription"),
            id=f"{PAYMENT_PREFIX}subscription_buy",
            state=Subscription.PLANS,
            data={"goto_buy": True},
            when=~F["has_active_subscription"],
        ),
        Start(
            text=I18nFormat("btn-menu.subscription"),
            id=f"{PAYMENT_PREFIX}subscription",
            state=Subscription.MAIN,
            when=F["has_active_subscription"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-menu.invite"),
            id="invite",
            on_click=on_invite,
            when=F["referral_enabled"],
        ),
        SwitchInlineQueryChosenChatButton(
            text=I18nFormat("btn-menu.invite"),
            query=Format(INLINE_QUERY_INVITE),
            allow_user_chats=True,
            allow_group_chats=True,
            allow_channel_chats=True,
            id="send",
            when=~F["referral_enabled"],
        ),
        # Support opens the onboarding "не получается" self-service screen (tips +
        # a support link inside) instead of jumping straight into the support DM.
        # `from_menu` tells that screen its Back button should return to the menu
        # (in the funnel the same screen goes Back to the connect step instead).
        Start(
            text=I18nFormat("btn-menu.support"),
            id="support",
            state=Onboarding.NOT_WORKING,
            data={"from_menu": True},
        ),
    ),
    *custom_buttons,
    Row(
        Start(
            text=I18nFormat("btn-menu.dashboard"),
            id="dashboard",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
            when=require_permission(Permission.VIEW_DASHBOARD),
        ),
    ),
    MessageInput(func=on_smart_search),
    IgnoreUpdate(),
    state=MainMenu.MAIN,
    getter=menu_getter,
)

devices = Window(
    Banner(BannerName.DEVICES),
    I18nFormat("msg-menu-devices"),
    # "Add device" opens the onboarding funnel and stays available until the device
    # limit is reached (spec fix #5/#15); at the limit it flips to "Изменить подписку"
    # (→ the Subscription screen), the only way to raise the cap.
    Row(
        Start(
            text=I18nFormat("btn-devices.add-device"),
            id="add_device",
            state=Onboarding.DEVICE_CHOICE,
            when=~F["at_device_limit"],
            style=Style(ButtonStyle.SUCCESS),
        ),
        Start(
            text=I18nFormat("btn-devices.change-subscription"),
            id="change_subscription",
            state=Subscription.MAIN,
            when=F["at_device_limit"],
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    ListGroup(
        Row(
            Button(
                text=Format("{item[label]}"),
                id="device_item",
                on_click=on_device_delete_request,
                when=F["data"]["device_single_enabled"],
                style=Style(ButtonStyle.PRIMARY),
            ),
            Button(
                text=Format("{item[label]}"),
                id="device_item_display",
                when=~F["data"]["device_single_enabled"],
                style=Style(ButtonStyle.PRIMARY),
            ),
        ),
        id="devices_list",
        item_id_getter=lambda item: item["index"],
        items="devices",
        when=F["has_devices"],
    ),
    Row(
        Start(
            text=I18nFormat("btn-devices.delete-all"),
            id="delete_all",
            state=MainMenu.DEVICE_CONFIRM_DELETE_ALL,
            when=F["has_devices"] & F["device_all_enabled"],
            style=Style(ButtonStyle.DANGER),
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-devices.reissue"),
            id="reissue",
            state=MainMenu.DEVICE_CONFIRM_REISSUE,
            style=Style(ButtonStyle.PRIMARY),
            when=F["link_reset_enabled"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.DEVICES,
    getter=devices_getter,
)

device_confirm_delete = Window(
    Banner(BannerName.DEVICE_REMOVE),
    I18nFormat("msg-menu-devices-confirm-delete"),
    Row(
        Button(
            text=I18nFormat("btn-devices.confirm-delete"),
            id="confirm_delete",
            on_click=on_device_delete_confirm,
            style=Style(ButtonStyle.DANGER),
        ),
        SwitchTo(
            text=I18nFormat("btn-common.cancel"),
            id="cancel",
            state=MainMenu.DEVICES,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.DEVICE_CONFIRM_DELETE,
    getter=device_confirm_delete_getter,
)

device_confirm_delete_all = Window(
    Banner(BannerName.DEVICE_REMOVE),
    I18nFormat("msg-menu-devices-confirm-delete-all"),
    Row(
        Button(
            text=I18nFormat("btn-devices.confirm-delete"),
            id="confirm_delete_all",
            on_click=on_device_delete_all_confirm,
            style=Style(ButtonStyle.DANGER),
        ),
        SwitchTo(
            text=I18nFormat("btn-common.cancel"),
            id="cancel",
            state=MainMenu.DEVICES,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.DEVICE_CONFIRM_DELETE_ALL,
    getter=device_confirm_delete_getter,
)

invite = Window(
    Banner(BannerName.REFERRAL),
    I18nFormat("msg-menu-invite"),
    # Money actions — one full-width green button per row (Вывести first). Вывести is
    # a Button (not SwitchTo): below the minimum it answers with a popup instead of
    # opening the screen. Both hide while a payout is open (locked, spec §3.3).
    Row(
        Button(
            text=I18nFormat("btn-invite.withdraw"),
            id="withdraw",
            on_click=on_invite_withdraw_click,
            style=Style(ButtonStyle.SUCCESS),
            when=~F["has_open_payout"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-invite.pay-vpn"),
            id="pay_vpn",
            state=MainMenu.INVITE_PAY,
            style=Style(ButtonStyle.SUCCESS),
            when=~F["has_open_payout"],
        ),
    ),
    # Blue row: invite (own screen, hides the QR) + about.
    Row(
        SwitchTo(
            text=I18nFormat("btn-invite.send"),
            id="share",
            state=MainMenu.INVITE_SHARE,
            style=Style(ButtonStyle.PRIMARY),
        ),
        SwitchTo(
            text=I18nFormat("btn-invite.about"),
            id="about",
            state=MainMenu.INVITE_ABOUT,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-invite.reset-referral"),
            id="reset_referral",
            on_click=on_reset_referral_code,
            when=F["referral_reset_enabled"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.INVITE,
    getter=invite_getter,
)

invite_share = Window(
    Banner(BannerName.REFERRAL),
    I18nFormat("msg-menu-invite-share"),
    Row(
        SwitchInlineQueryChosenChatButton(
            text=I18nFormat("btn-invite.share-link"),
            query=Format(INLINE_QUERY_INVITE),
            allow_user_chats=True,
            allow_group_chats=True,
            allow_channel_chats=True,
            id="send",
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-invite.qr"),
            id="qr",
            on_click=on_show_qr,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.INVITE,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.INVITE_SHARE,
)

invite_about = Window(
    Banner(BannerName.REFERRAL),
    I18nFormat("msg-menu-invite-about"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.INVITE,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.INVITE_ABOUT,
    getter=invite_about_getter,
)

invite_withdraw_method = Window(
    Banner(BannerName.REFERRAL),
    I18nFormat("msg-menu-invite-withdraw-method"),
    # Both methods are always offered; each button guards its own preconditions
    # (crypto min / linked Telegram + stars min) with an explanatory popup.
    Row(
        Button(
            text=I18nFormat("btn-invite.withdraw-crypto"),
            id="wd_crypto",
            on_click=on_withdraw_method_crypto,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-invite.withdraw-stars"),
            id="wd_stars",
            on_click=on_withdraw_method_stars,
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.INVITE,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.INVITE_WITHDRAW_METHOD,
    getter=invite_withdraw_method_getter,
)

invite_withdraw = Window(
    Banner(BannerName.REFERRAL),
    I18nFormat("msg-menu-invite-withdraw"),
    MessageInput(on_withdraw_wallet_input),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.INVITE,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.INVITE_WITHDRAW,
    getter=invite_withdraw_getter,
)

invite_withdraw_stars = Window(
    Banner(BannerName.REFERRAL),
    I18nFormat("msg-menu-invite-withdraw-stars"),
    Row(
        Button(
            text=I18nFormat("btn-invite.confirm-stars"),
            id="confirm_stars",
            on_click=on_stars_withdraw_confirm,
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.INVITE_WITHDRAW_METHOD,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.INVITE_WITHDRAW_STARS,
    getter=invite_withdraw_stars_getter,
)

invite_pay = Window(
    Banner(BannerName.REFERRAL),
    I18nFormat("msg-menu-invite-pay"),
    Column(
        Select(
            text=Format("{item[label]}"),
            id="pay_select",
            item_id_getter=lambda item: item["id"],
            items="pay_items",
            on_click=on_pay_with_balance_select,
        ),
        when=F["has_items"],
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=MainMenu.INVITE,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.INVITE_PAY,
    getter=invite_pay_getter,
)


device_confirm_reissue = Window(
    Banner(BannerName.MENU),
    I18nFormat("msg-menu-devices-confirm-reissue"),
    Row(
        Button(
            text=I18nFormat("btn-devices.confirm-reissue"),
            id="confirm_reissue",
            on_click=on_reissue_subscription_confirm,
            style=Style(ButtonStyle.DANGER),
        ),
        SwitchTo(
            text=I18nFormat("btn-devices.cancel-reissue"),
            id="cancel_reissue",
            state=MainMenu.DEVICES,
        ),
    ),
    IgnoreUpdate(),
    state=MainMenu.DEVICE_CONFIRM_REISSUE,
    getter=device_confirm_delete_getter,
)

router = Dialog(
    menu,
    devices,
    device_confirm_delete,
    device_confirm_delete_all,
    device_confirm_reissue,
    invite,
    invite_about,
    invite_share,
    invite_withdraw_method,
    invite_withdraw,
    invite_withdraw_stars,
    invite_pay,
)
