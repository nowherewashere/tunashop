from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from adaptix import Retort
from aiogram_dialog import DialogManager
from aiogram_dialog.api.exceptions import UnknownIntent
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import TranslatorRunner
from src.application.common.dao import PaymentGatewayDao, PlanDao, SettingsDao, SubscriptionDao
from src.application.dto import PaymentGatewayDto, PlanDto, PriceDetailsDto, TelegramUserDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.application.services import PricingService
from src.application.use_cases.plan.queries.match import MatchPlan, MatchPlanDto
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.config import AppConfig
from src.core.enums import PaymentGatewayType, PlategaPaymentMethod, PurchaseType
from src.core.utils.i18n_helpers import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.telegram.utils import translate_or_literal
from src.telegram.widgets.banner import plan_banner_candidates


def _get_gateway_title(i18n: TranslatorRunner, gateway: PaymentGatewayDto) -> str:
    if gateway.settings and gateway.settings.display_name:
        return gateway.settings.display_name

    return i18n.get("gateway-type", gateway_type=gateway.type)


def _build_durations_info(i18n: TranslatorRunner, durations: list[dict[str, Any]]) -> str:
    """Render the duration list with a computed term-savings % (spec fix #9).

    The discount for each term is its saving against the shortest term's per-day
    rate (rounded), so the labels always follow the plan's configured prices —
    nothing is stored or maintained by hand.
    """
    if not durations:
        return ""

    base = min(durations, key=lambda d: d["days"])
    base_days: int = base["days"]
    base_amount = Decimal(str(base["final_amount"]))
    base_per_day = base_amount / base_days if base_days else Decimal(0)

    lines = []
    for duration in durations:
        final = Decimal(str(duration["final_amount"]))
        expected = base_per_day * duration["days"]
        discount = 0
        if expected > 0 and final < expected:
            discount = int(
                ((expected - final) / expected * 100).to_integral_value(rounding=ROUND_HALF_UP)
            )
        lines.append(
            i18n.get(
                "frg-duration-line",
                period=duration["period"],
                amount=duration["final_amount"],
                currency=duration["currency"],
                discount=discount,
            )
        )
    return "\n".join(lines)


@inject
async def subscription_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    i18n: FromDishka[TranslatorRunner],
    subscription_dao: FromDishka[SubscriptionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)
    has_active = bool(current_subscription and not current_subscription.is_trial)
    is_unlimited = current_subscription.is_unlimited if current_subscription else False

    # Show the active plan's card above renew/change (spec fix #20), same shape as
    # the plan-selection screen (frg-plan-card with shared locations).
    subscription_info = ""
    banner_candidates: tuple[str, ...] = ()
    if has_active and current_subscription is not None:
        snapshot = current_subscription.plan_snapshot
        plan_name = translate_or_literal(i18n, snapshot.name)
        subscription_info = i18n.get(
            "frg-plan-card",
            name=plan_name,
            traffic=i18n_format_traffic_limit(current_subscription.traffic_limit),
            devices=i18n_format_device_limit(current_subscription.device_limit),
            locations=config.plan_locations,
        )
        # DataBanner shows the current plan's own image here (→ choose_sub → default).
        banner_candidates = plan_banner_candidates(plan_name, snapshot.id)

    return {
        "has_active_subscription": int(has_active),
        "is_not_unlimited": not is_unlimited,
        "subscription_info": subscription_info,
        "banner_candidates": banner_candidates,
    }


@inject
async def plan_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    i18n: FromDishka[TranslatorRunner],
    plan_dao: FromDishka[PlanDao],
    subscription_dao: FromDishka[SubscriptionDao],
    match_plan: FromDishka[MatchPlan],
    **kwargs: Any,
) -> dict[str, Any]:
    plan_id: int = dialog_manager.start_data["plan_id"]  # type: ignore[call-overload, index, assignment]
    plan = await plan_dao.get_by_id(plan_id)

    if not plan:
        raise ValueError(f"Plan with id '{plan_id}' not found")

    current_subscription = await subscription_dao.get_current(user.id)

    if current_subscription:
        matched_plan = await match_plan.system(
            MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=[plan])
        )

        if matched_plan and not current_subscription.is_unlimited:
            purchase_type = PurchaseType.RENEW
        else:
            purchase_type = PurchaseType.CHANGE
    else:
        purchase_type = PurchaseType.NEW

    dialog_manager.dialog_data["only_single_plan"] = True
    dialog_manager.dialog_data["purchase_type"] = purchase_type

    return {
        "plan_id": [plan.id],
        "name": translate_or_literal(i18n, plan.name),
        "description": translate_or_literal(i18n, plan.description) if plan.description else False,
        "purchase_type": purchase_type,
        # Per-plan banner (fix.txt #7) — falls back to choose_sub then default.
        "banner_candidates": plan_banner_candidates(translate_or_literal(i18n, plan.name), plan.id),
    }


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    i18n: FromDishka[TranslatorRunner],
    get_available_plans: FromDishka[GetAvailablePlans],
    **kwargs: Any,
) -> dict[str, Any]:
    plans = await get_available_plans.system(user)

    # Locations are shared identically across all plans and editable via env
    # (APP_PLAN_LOCATIONS), so the list stays in sync without per-plan config.
    locations = config.plan_locations

    formatted_plans = [
        {
            "id": plan.id,
            "name": translate_or_literal(i18n, plan.name),
        }
        for plan in plans
    ]

    # Pre-render one card per plan (spec fix #8) — a dynamic list can't be looped
    # inside fluent, so it is assembled here and injected as { $plans_info }.
    # Cards are separated by a blank line for readability.
    plans_info = "\n\n".join(
        i18n.get(
            "frg-plan-card",
            name=translate_or_literal(i18n, plan.name),
            traffic=i18n_format_traffic_limit(plan.traffic_limit),
            devices=i18n_format_device_limit(plan.device_limit),
            locations=locations,
        )
        for plan in plans
    )

    return {
        "plans": formatted_plans,
        "plans_info": plans_info,
    }


@inject
async def duration_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    pricing_service: FromDishka[PricingService],
    **kwargs: Any,
) -> dict[str, Any]:
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        raise UnknownIntent("PlanDto not found in subscription dialog data")

    plan = retort.load(raw_plan, PlanDto)
    settings = await settings_dao.get()
    currency = settings.default_currency
    only_single_plan = dialog_manager.dialog_data.get("only_single_plan", False)
    dialog_manager.dialog_data["is_free"] = False
    durations = []

    # Deterministic display order for every plan: the admin-controlled order_index
    # first, then ascending days as the tie-break. New plans (all order_index == 0)
    # therefore show 1/3/6/12 automatically without any admin reordering, while a
    # plan whose durations were reordered in the dashboard keeps that order.
    ordered_durations = sorted(plan.durations, key=lambda d: (d.order_index, d.days))

    for duration in ordered_durations:
        key, kw = i18n_format_days(duration.days)
        price = pricing_service.calculate(user, duration.get_price(currency), currency)
        durations.append(
            {
                "days": duration.days,
                "period": i18n.get(key, **kw),
                "final_amount": price.final_amount,
                "discount_percent": price.discount_percent,
                "original_amount": price.original_amount,
                "currency": currency.symbol,
            }
        )

    # Term-savings % (spec fix #9): compute each duration's discount vs the shortest
    # term's per-day rate, so the "(−N%)" labels always track the configured prices.
    durations_info = _build_durations_info(i18n, durations)

    plan_is_modified = 1 if dialog_manager.dialog_data.get("plan_is_modified", False) else 0

    return {
        "plan": translate_or_literal(i18n, plan.name),
        "description": translate_or_literal(i18n, plan.description) if plan.description else False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "durations": durations,
        "durations_info": durations_info,
        "period": 0,
        "final_amount": 0,
        "currency": "",
        "only_single_plan": only_single_plan,
        "discount_percent": pricing_service.get_effective_discount(user),
        "is_personal_discount": pricing_service.is_largest_discount_personal(user),
        "plan_is_modified": plan_is_modified,
        # Per-plan banner (fix.txt #7) — falls back to choose_sub then default.
        "banner_candidates": plan_banner_candidates(translate_or_literal(i18n, plan.name), plan.id),
    }


def _pay_state(
    dialog_manager: DialogManager,
    retort: Retort,
    gateways: list[PaymentGatewayDto],
) -> dict[str, Any]:
    """Pay-state read from dialog_data once a payment is created — the confirmation
    screen is merged into the method screen. ``url`` is None while still choosing, and
    the window then shows the method list instead of the «Оплатить» button."""
    url = dialog_manager.dialog_data.get("payment_url")
    # A created payment with no redirect url is a free (100%-discount) grant -> the
    # «Получить» button. Derived from the payment state so it's correct on every entry
    # path (the dialog_data["is_free"] flag isn't set on the fully-collapsed path).
    is_free = bool(dialog_manager.dialog_data.get("payment_id")) and not url
    raw_pricing = dialog_manager.dialog_data.get("final_pricing")
    final_amount: Any = 0
    original_amount: Any = 0
    discount_percent = 0
    currency = ""
    if url and raw_pricing:
        pricing = retort.load(raw_pricing, PriceDetailsDto)
        final_amount = pricing.final_amount
        original_amount = pricing.original_amount
        discount_percent = pricing.discount_percent
        selected = dialog_manager.dialog_data.get("selected_payment_method")
        gateway = next((g for g in gateways if g.type == selected), None)
        currency = gateway.currency.symbol if gateway else ""
    return {
        "url": url,
        "is_free": is_free,
        "final_amount": final_amount,
        "original_amount": original_amount,
        "discount_percent": discount_percent,
        "currency": currency,
    }


@inject
async def payment_method_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    **kwargs: Any,
) -> dict[str, Any]:
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        raise UnknownIntent("PlanDto not found in subscription dialog data")

    plan = retort.load(raw_plan, PlanDto)
    gateways = await payment_gateway_dao.get_active()
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    only_single_duration = dialog_manager.dialog_data.get("only_single_duration", False)
    duration = plan.get_duration(selected_duration)

    if not duration:
        raise ValueError(f"Duration '{selected_duration}' not found in plan '{plan.name}'")

    payment_methods = []
    for gateway in gateways:
        raw_price = duration.get_price(gateway.currency)
        price = pricing_service.calculate(
            user, raw_price, gateway.currency, apply_discount=not plan.is_trial
        )
        payment_methods.append(
            {
                "gateway_type": gateway.type,
                "gateway_title": _get_gateway_title(i18n, gateway),
                "final_amount": price.final_amount,
                "original_amount": price.original_amount,
                "discount_percent": price.discount_percent,
                "currency": gateway.currency.symbol,
            }
        )

    key, kw = i18n_format_days(duration.days)

    plan_is_modified = 1 if dialog_manager.dialog_data.get("plan_is_modified", False) else 0
    pay = _pay_state(dialog_manager, retort, gateways)

    return {
        "plan": translate_or_literal(i18n, plan.name),
        "description": translate_or_literal(i18n, plan.description) if plan.description else False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "period": i18n.get(key, **kw),
        "payment_methods": payment_methods,
        # Cost line only appears once a payment exists (pay-state); before that the
        # per-gateway prices live on the method buttons.
        "final_amount": pay["final_amount"],
        "original_amount": pay["original_amount"],
        "currency": pay["currency"],
        "url": pay["url"],
        "is_free": pay["is_free"],
        "purchase_type": dialog_manager.dialog_data.get("purchase_type"),
        "only_single_duration": only_single_duration,
        "only_single_plan": dialog_manager.dialog_data.get("only_single_plan", False),
        "only_single_gateway": len(gateways) == 1,
        "discount_percent": (
            pay["discount_percent"]
            if pay["url"]
            else (0 if plan.is_trial else pricing_service.get_effective_discount(user))
        ),
        "is_personal_discount": (
            False if plan.is_trial else pricing_service.is_largest_discount_personal(user)
        ),
        "plan_is_modified": plan_is_modified,
    }


@inject
async def platega_method_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    **kwargs: Any,
) -> dict[str, Any]:
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        raise UnknownIntent("PlanDto not found in subscription dialog data")

    plan = retort.load(raw_plan, PlanDto)
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    duration = plan.get_duration(selected_duration)

    if not duration:
        raise ValueError(f"Duration '{selected_duration}' not found in plan '{plan.name}'")

    gateway = await payment_gateway_dao.get_by_type(PaymentGatewayType.PLATEGA)
    if not gateway or not isinstance(gateway.settings, PlategaGatewaySettingsDto):
        raise ValueError("Platega gateway is not configured")

    active_gateways = await payment_gateway_dao.get_active()

    price = pricing_service.calculate(
        user,
        duration.get_price(gateway.currency),
        gateway.currency,
        apply_discount=not plan.is_trial,
    )

    configs = {m.id: m for m in (gateway.settings.methods or [])}
    methods = [
        {
            "id": method.value,
            "label": configs[method.value].label or method.default_label,
        }
        for method in PlategaPaymentMethod
        if configs.get(method.value) and configs[method.value].enabled
    ]

    key, kw = i18n_format_days(duration.days)
    pay = _pay_state(dialog_manager, retort, [gateway])

    return {
        "plan": translate_or_literal(i18n, plan.name),
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "period": i18n.get(key, **kw),
        "final_amount": price.final_amount,
        "currency": gateway.currency.symbol,
        "methods": methods,
        "url": pay["url"],
        "purchase_type": dialog_manager.dialog_data.get("purchase_type"),
        "only_single_gateway": len(active_gateways) == 1,
        "only_single_duration": dialog_manager.dialog_data.get("only_single_duration", False),
        "only_single_plan": dialog_manager.dialog_data.get("only_single_plan", False),
    }


@inject
async def getter_connect(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)

    if not current_subscription:
        raise ValueError(f"User '{user.telegram_id}' has no active subscription after purchase")

    settings = await settings_dao.get()

    return {
        "is_mini_app": config.bot.is_mini_app,
        "is_mini_app_reserve": config.bot.is_mini_app and settings.extra.mini_app_reserve,
        "onboarding_enabled": settings.extra.onboarding_enabled,
        "connection_url": config.bot.mini_app_url or current_subscription.url,
        "subscription_url": current_subscription.url,
        "connectable": True,
    }


@inject
async def success_payment_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    settings_dao: FromDishka[SettingsDao],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    start_data = cast(dict[str, Any], dialog_manager.start_data)
    purchase_type: PurchaseType = start_data["purchase_type"]
    subscription = await subscription_dao.get_current(user.id)

    if not subscription:
        raise ValueError(f"User '{user.telegram_id}' has no active subscription after purchase")

    settings = await settings_dao.get()

    return {
        "purchase_type": purchase_type,
        "plan_name": translate_or_literal(i18n, subscription.plan_snapshot.name),
        "traffic_limit": i18n_format_traffic_limit(subscription.traffic_limit),
        "device_limit": i18n_format_device_limit(subscription.device_limit),
        "expire_time": i18n_format_expire_time(subscription.expire_at),
        "added_duration": i18n_format_days(subscription.plan_snapshot.duration),
        "is_mini_app": config.bot.is_mini_app,
        "is_mini_app_reserve": config.bot.is_mini_app and settings.extra.mini_app_reserve,
        "onboarding_enabled": settings.extra.onboarding_enabled,
        "connection_url": config.bot.mini_app_url or subscription.url,
        "subscription_url": subscription.url,
        "connectable": True,
    }
