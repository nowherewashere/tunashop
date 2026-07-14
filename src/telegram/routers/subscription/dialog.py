from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Format
from magic_filter import F

from src.core.constants import PAYMENT_PREFIX
from src.core.enums import BannerName, PaymentGatewayType, PurchaseType
from src.telegram.keyboards import (
    back_main_menu_button,
    connect_buttons,
    onboarding_connect_buttons,
)
from src.telegram.states import Subscription
from src.telegram.widgets import Banner, DataBanner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Column, Group, Row, Select, SwitchTo, Url

from .getters import (
    confirm_getter,
    duration_getter,
    getter_connect,
    payment_method_getter,
    plan_getter,
    plans_getter,
    platega_method_getter,
    subscription_getter,
    success_payment_getter,
)
from .handlers import (
    on_duration_select,
    on_get_subscription,
    on_payment_method_select,
    on_plan_select,
    on_platega_method_select,
    on_subscription_plans,
    on_subscription_start,
)
from .promocode_handlers import getter_promocode, on_promocode_confirm, on_promocode_input

subscription = Window(
    DataBanner(),
    I18nFormat("msg-subscription-main"),
    Row(
        Button(
            text=I18nFormat("btn-subscription.new"),
            id=f"{PAYMENT_PREFIX}{PurchaseType.NEW}",
            on_click=on_subscription_plans,
            when=~F["has_active_subscription"],
        ),
        Button(
            text=I18nFormat("btn-subscription.renew"),
            id=f"{PAYMENT_PREFIX}{PurchaseType.RENEW}",
            on_click=on_subscription_plans,
            when=F["has_active_subscription"] & F["is_not_unlimited"],
            style=Style(ButtonStyle.SUCCESS),
        ),
        Button(
            text=I18nFormat("btn-subscription.change"),
            id=f"{PAYMENT_PREFIX}{PurchaseType.CHANGE}",
            on_click=on_subscription_plans,
            when=F["has_active_subscription"],
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    # Promocode entry hidden for now (per product decision). The PROMOCODE screen
    # and its handlers are left intact — restore this Row to re-enable it.
    # Row(
    #     Button(
    #         text=I18nFormat("btn-subscription.promocode"),
    #         id="goto_promocode",
    #         on_click=lambda c, w, m: m.switch_to(Subscription.PROMOCODE),
    #     ),
    # ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.MAIN,
    getter=subscription_getter,
)

plan = Window(
    DataBanner(),
    I18nFormat("msg-subscription-plan"),
    Column(
        Select(
            text=I18nFormat("btn-subscription.plan"),
            id=f"{PAYMENT_PREFIX}select_plan",
            item_id_getter=lambda item: item,
            items="plan_id",
            type_factory=int,
            on_click=on_plan_select,
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.PLAN,
    getter=plan_getter,
)


plans = Window(
    Banner(BannerName.CHOOSE_SUB),
    I18nFormat("msg-subscription-plans"),
    Column(
        # Plan buttons in the brand blue (spec fix #21). Per-plan colours (e.g. a
        # premium Pro tint) aren't possible yet — Telegram only exposes PRIMARY /
        # SUCCESS / DANGER, and there's no per-plan colour field to key off.
        Select(
            text=Format("{item[name]}"),
            id=f"{PAYMENT_PREFIX}select_plan",
            item_id_getter=lambda item: item["id"],
            items="plans",
            type_factory=int,
            on_click=on_plan_select,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id=f"{PAYMENT_PREFIX}back",
            state=Subscription.MAIN,
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.PLANS,
    getter=plans_getter,
)

duration = Window(
    DataBanner(),
    I18nFormat("msg-subscription-duration"),
    Group(
        Select(
            text=I18nFormat(
                "btn-subscription.duration",
                period=F["item"]["period"],
                final_amount=F["item"]["final_amount"],
                discount_percent=F["item"]["discount_percent"],
                original_amount=F["item"]["original_amount"],
                currency=F["item"]["currency"],
            ),
            id=f"{PAYMENT_PREFIX}select_duration",
            item_id_getter=lambda item: item["days"],
            items="durations",
            type_factory=int,
            on_click=on_duration_select,
            # Duration buttons in the brand blue (fix.txt #3); the navigation
            # buttons below stay the default colour.
            style=Style(ButtonStyle.PRIMARY),
        ),
        # One duration per row (spec fix #6) — the "period | price" label overflows
        # a 2-column layout on narrow phones.
        width=1,
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-subscription.back-plans"),
            id=f"{PAYMENT_PREFIX}back_plans",
            state=Subscription.PLANS,
            when=~F["only_single_plan"],
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.DURATION,
    getter=duration_getter,
)

payment_method = Window(
    Banner(BannerName.PAYMENT_METHOD),
    I18nFormat("msg-subscription-payment-method"),
    Column(
        Select(
            text=I18nFormat(
                "btn-subscription.payment-method",
                gateway_title=F["item"]["gateway_title"],
                final_amount=F["item"]["final_amount"],
                original_amount=F["item"]["original_amount"],
                discount_percent=F["item"]["discount_percent"],
                currency=F["item"]["currency"],
            ),
            id=f"{PAYMENT_PREFIX}select_payment_method",
            item_id_getter=lambda item: item["gateway_type"],
            items="payment_methods",
            type_factory=PaymentGatewayType,
            on_click=on_payment_method_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-subscription.back-duration"),
            id=f"{PAYMENT_PREFIX}back",
            state=Subscription.DURATION,
            when=~F["only_single_duration"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-subscription.back-plans"),
            id=f"{PAYMENT_PREFIX}back_plans",
            state=Subscription.PLANS,
            when=~F["only_single_plan"],
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.PAYMENT_METHOD,
    getter=payment_method_getter,
)

platega_method = Window(
    Banner(BannerName.PAYMENT_METHOD),
    I18nFormat("msg-subscription-platega-method"),
    Column(
        Select(
            text=Format("{item[label]}"),
            id=f"{PAYMENT_PREFIX}select_platega_method",
            item_id_getter=lambda item: item["id"],
            items="methods",
            type_factory=int,
            on_click=on_platega_method_select,
            style=Style(ButtonStyle.PRIMARY),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-subscription.back-payment-method"),
            id=f"{PAYMENT_PREFIX}back_pm",
            state=Subscription.PAYMENT_METHOD,
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.PLATEGA_METHOD,
    getter=platega_method_getter,
)

confirm = Window(
    DataBanner(),
    I18nFormat("msg-subscription-confirm"),
    Row(
        Url(
            text=I18nFormat("btn-subscription.pay"),
            url=Format("{url}"),
            when=F["url"],
            style=Style(ButtonStyle.SUCCESS),
        ),
        Button(
            text=I18nFormat("btn-subscription.get"),
            id=f"{PAYMENT_PREFIX}get",
            on_click=on_get_subscription,
            when=~F["url"],
            style=Style(ButtonStyle.SUCCESS),
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-subscription.back-payment-method"),
            id=f"{PAYMENT_PREFIX}back_payment_method",
            state=Subscription.PAYMENT_METHOD,
            when=~F["only_single_gateway"] & ~F["is_free"],
        ),
        SwitchTo(
            text=I18nFormat("btn-subscription.back-duration"),
            id=f"{PAYMENT_PREFIX}back_duration",
            state=Subscription.DURATION,
            when=F["only_single_gateway"] & ~F["only_single_duration"] | F["is_free"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-subscription.back-plans"),
            id=f"{PAYMENT_PREFIX}back_plans",
            state=Subscription.PLANS,
            when=~F["only_single_plan"],
        ),
    ),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.CONFIRM,
    getter=confirm_getter,
)

success_payment = Window(
    Banner(BannerName.SUCCESS),
    I18nFormat("msg-subscription-success"),
    *connect_buttons,
    *onboarding_connect_buttons,
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.SUCCESS,
    getter=success_payment_getter,
)

success_trial = Window(
    DataBanner(),
    I18nFormat("msg-subscription-trial"),
    *connect_buttons,
    *onboarding_connect_buttons,
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.TRIAL,
    getter=getter_connect,
)

failed = Window(
    DataBanner(),
    I18nFormat("msg-subscription-failed"),
    *back_main_menu_button,
    IgnoreUpdate(),
    state=Subscription.FAILED,
)

promocode_window = Window(
    Banner(BannerName.PROMOCODE),
    I18nFormat("msg-promocode-input", ~F["has_promo"]),
    I18nFormat(
        "msg-promocode-confirm",
        F["has_promo"],
        promo_code=F["promo_code"],
        reward_type=F["promo_reward_type"],
        reward=F["promo_reward"],
        show_reset_warning=F["show_reset_warning"],
        will_replace_subscription=F["will_replace_subscription"],
    ),
    MessageInput(on_promocode_input),
    Row(
        Button(
            text=I18nFormat("btn-subscription.promocode-confirm"),
            id="confirm_promo",
            on_click=on_promocode_confirm,
            when=F["has_promo"],
        ),
    ),
    SwitchTo(
        text=I18nFormat("btn-back.general"),
        id="back_main",
        state=Subscription.MAIN,
    ),
    state=Subscription.PROMOCODE,
    getter=getter_promocode,
)

router = Dialog(
    subscription,
    promocode_window,
    plan,
    plans,
    duration,
    payment_method,
    platega_method,
    confirm,
    success_payment,
    success_trial,
    failed,
    on_start=on_subscription_start,
)
