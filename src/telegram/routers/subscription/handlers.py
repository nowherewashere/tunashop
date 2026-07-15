from typing import Any, Optional, TypedDict, cast

from adaptix import Retort
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.common.dao import PaymentGatewayDao, PlanDao, SettingsDao, SubscriptionDao
from src.application.dto import PlanDto, PlanSnapshotDto, SubscriptionDto, TelegramUserDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.application.services import PricingService
from src.application.use_cases.gateways.commands.payment import (
    CreatePayment,
    CreatePaymentDto,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.plan.queries.match import MatchPlan, MatchPlanDto
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.constants import PAYMENT_PREFIX, USER_KEY
from src.core.enums import PaymentGatewayType, PurchaseType, TransactionStatus
from src.telegram.states import Subscription


async def on_subscription_start(start_data: Any, manager: DialogManager) -> None:
    if isinstance(start_data, dict) and start_data.get("goto_buy"):
        # New/trial user opened "Подписка" from the menu: the dialog is started
        # directly at the plan list (Subscription.PLANS), skipping the MAIN chooser.
        # For them the purchase is always NEW; downstream steps read this from
        # dialog_data (on_plan_select onward), so it must be set before rendering.
        manager.dialog_data["purchase_type"] = PurchaseType.NEW
        return

    if not start_data or "trial_plan" not in start_data:
        return

    manager.dialog_data[PlanDto.__name__] = start_data["trial_plan"]
    manager.dialog_data["purchase_type"] = PurchaseType.NEW
    manager.dialog_data["selected_duration"] = start_data["trial_duration"]
    manager.dialog_data["only_single_plan"] = True
    manager.dialog_data["only_single_duration"] = True
    manager.dialog_data["is_free"] = False

    await manager.switch_to(Subscription.PAYMENT_METHOD)


PAYMENT_CACHE_KEY = "payment_cache"
CURRENT_DURATION_KEY = "selected_duration"
CURRENT_METHOD_KEY = "selected_payment_method"


class CachedPaymentData(TypedDict):
    payment_id: str
    payment_url: Optional[str]
    final_pricing: str


def _get_cache_key(
    duration: int,
    gateway_type: PaymentGatewayType,
    purchase_type: PurchaseType,
    payment_method: Optional[int] = None,
) -> str:
    # payment_method keeps two Platega sub-methods (e.g. СБП vs крипта) from colliding
    # on one cached payment URL.
    return f"{purchase_type}:{duration}:{gateway_type.value}:{payment_method}"


def _load_payment_data(dialog_manager: DialogManager) -> dict[str, CachedPaymentData]:
    if PAYMENT_CACHE_KEY not in dialog_manager.dialog_data:
        dialog_manager.dialog_data[PAYMENT_CACHE_KEY] = {}
    return cast(dict[str, CachedPaymentData], dialog_manager.dialog_data[PAYMENT_CACHE_KEY])


def _save_payment_data(dialog_manager: DialogManager, payment_data: CachedPaymentData) -> None:
    dialog_manager.dialog_data["payment_id"] = payment_data["payment_id"]
    dialog_manager.dialog_data["payment_url"] = payment_data["payment_url"]
    dialog_manager.dialog_data["final_pricing"] = payment_data["final_pricing"]


def _clear_payment_state(dialog_manager: DialogManager) -> None:
    # Drop the active pay-state so the method screen shows the method list again (the
    # confirmation screen is merged into the method screen — the «Оплатить» button is
    # shown only while payment_url is set for the current selection).
    for key in ("payment_id", "payment_url", "final_pricing"):
        dialog_manager.dialog_data.pop(key, None)


async def _create_payment_and_get_data(
    dialog_manager: DialogManager,
    plan: PlanDto,
    duration_days: int,
    gateway_type: PaymentGatewayType,
    retort: Retort,
    payment_gateway_dao: PaymentGatewayDao,
    notifier: Notifier,
    pricing_service: PricingService,
    create_payment: CreatePayment,
    payment_method: Optional[int] = None,
) -> Optional[CachedPaymentData]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    duration = plan.get_duration(duration_days)
    payment_gateway = await payment_gateway_dao.get_by_type(gateway_type)
    purchase_type: PurchaseType = dialog_manager.dialog_data["purchase_type"]

    if not duration or not payment_gateway:
        logger.error(f"{user.log} Failed to find duration or gateway for payment creation")
        return None

    pricing = pricing_service.calculate_for_duration(
        user, duration, payment_gateway.currency, apply_discount=not plan.is_trial
    )
    # Capture the paid amount in the snapshot so a later plan change can prorate the
    # remaining value into bonus days (SubscriptionProrationService).
    transaction_plan = PlanSnapshotDto.from_plan(
        plan,
        duration.days,
        price=pricing.final_amount,
        price_currency=payment_gateway.currency,
    )

    try:
        result = await create_payment(
            user,
            CreatePaymentDto(
                plan_snapshot=transaction_plan,
                pricing=pricing,
                purchase_type=purchase_type,
                gateway_type=gateway_type,
                payment_method=payment_method,
            ),
        )

        return CachedPaymentData(
            payment_id=str(result.id),
            payment_url=result.url,
            final_pricing=retort.dump(pricing),
        )

    except Exception:
        logger.error(f"{user.log} Failed to create payment")
        await notifier.notify_user(user, i18n_key="ntf-subscription.payment-creation-failed")
        raise


async def _resolve_platega_method(
    dialog_manager: DialogManager,
    plan: PlanDto,
    duration_days: int,
    gateway_type: PaymentGatewayType,
    payment_gateway_dao: PaymentGatewayDao,
    pricing_service: PricingService,
    user: TelegramUserDto,
) -> tuple[bool, Optional[int]]:
    """Decide how a Platega selection proceeds.

    Returns ``(routed, payment_method)``:
    - ``(True, None)``  — switched to the in-bot method picker; the caller must return.
    - ``(False, id)``   — exactly one method is enabled; create the payment with it.
    - ``(False, None)`` — not Platega / hard-pinned / no methods / free: proceed as usual.
    """
    if gateway_type != PaymentGatewayType.PLATEGA:
        return False, None

    gateway = await payment_gateway_dao.get_by_type(gateway_type)
    if not gateway or not isinstance(gateway.settings, PlategaGatewaySettingsDto):
        return False, None
    settings = gateway.settings

    # Admin hard-pin wins: the gateway applies settings.payment_method itself.
    if settings.payment_method is not None:
        return False, None

    enabled = settings.enabled_methods()
    if not enabled:
        return False, None  # fall back to Platega's own multi-method page
    if len(enabled) == 1:
        return False, enabled[0].id  # single method -> apply it silently

    # 2+ methods: no picker for free purchases (no Platega call happens at all).
    duration = plan.get_duration(duration_days)
    if duration is None:
        return False, None
    price = pricing_service.calculate_for_duration(
        user, duration, gateway.currency, apply_discount=not plan.is_trial
    )
    if price.is_free:
        return False, None

    dialog_manager.dialog_data[CURRENT_METHOD_KEY] = gateway_type
    _clear_payment_state(dialog_manager)
    await dialog_manager.switch_to(state=Subscription.PLATEGA_METHOD)
    return True, None


async def _resolve_renew_plan(
    user: TelegramUserDto,
    dialog_manager: DialogManager,
    current_subscription: Optional[SubscriptionDto],
    plans: list[PlanDto],
    match_plan: MatchPlan,
    notifier: Notifier,
    retort: Retort,
) -> bool:
    if not current_subscription:
        return False

    matched_plan = await match_plan.system(
        MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=plans)
    )
    if matched_plan:
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(matched_plan)
        dialog_manager.dialog_data["only_single_plan"] = True
        dialog_manager.dialog_data["plan_is_modified"] = False
        await dialog_manager.switch_to(state=Subscription.DURATION)
        return True

    snapshot_id = current_subscription.plan_snapshot.id
    modified_plan = next((p for p in plans if p.id == snapshot_id), None)
    if modified_plan:
        logger.info(
            f"{user.log} Plan '{snapshot_id}' was modified, allowing renewal with updated data"
        )
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(modified_plan)
        dialog_manager.dialog_data["only_single_plan"] = True
        dialog_manager.dialog_data["plan_is_modified"] = True
        await dialog_manager.switch_to(state=Subscription.DURATION)
        return True

    logger.warning(f"{user.log} Tried to renew, but no matching plan found")
    await notifier.notify_user(user, i18n_key="ntf-subscription.renew-plan-unavailable")
    return True


@inject
async def on_purchase_type_select(
    purchase_type: PurchaseType,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    subscription_dao: FromDishka[SubscriptionDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
    match_plan: FromDishka[MatchPlan],
    get_available_plans: FromDishka[GetAvailablePlans],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plans: list[PlanDto] = await get_available_plans.system(user)
    gateways = await payment_gateway_dao.get_active()
    dialog_manager.dialog_data["purchase_type"] = purchase_type
    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)
    dialog_manager.dialog_data.pop(PAYMENT_CACHE_KEY, None)

    if not plans:
        logger.warning(f"{user.log} No available subscription plans")
        await notifier.notify_user(user, i18n_key="ntf-subscription.plans-unavailable")
        return

    if not gateways:
        logger.warning(f"{user.log} No active payment gateways")
        await notifier.notify_user(user, i18n_key="ntf-subscription.gateways-unavailable")
        return

    current_subscription = await subscription_dao.get_current(user.id)

    if purchase_type == PurchaseType.RENEW:
        if await _resolve_renew_plan(
            user, dialog_manager, current_subscription, plans, match_plan, notifier, retort
        ):
            return

    if len(plans) == 1:
        logger.info(f"{user.log} Auto-selected single plan '{plans[0].id}'")
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plans[0])
        dialog_manager.dialog_data["only_single_plan"] = True
        await dialog_manager.switch_to(state=Subscription.DURATION)
        return

    dialog_manager.dialog_data["only_single_plan"] = False
    await dialog_manager.switch_to(state=Subscription.PLANS)


@inject
async def on_subscription_plans(  # noqa: C901
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    subscription_dao: FromDishka[SubscriptionDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    notifier: FromDishka[Notifier],
    match_plan: FromDishka[MatchPlan],
    get_available_plans: FromDishka[GetAvailablePlans],
    create_payment: FromDishka[CreatePayment],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Opened subscription plans menu")

    plans: list[PlanDto] = await get_available_plans.system(user)
    gateways = await payment_gateway_dao.get_active()

    if not callback.data:
        raise ValueError("Callback data is empty")

    purchase_type = PurchaseType(callback.data.removeprefix(PAYMENT_PREFIX))
    dialog_manager.dialog_data["purchase_type"] = purchase_type

    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)
    dialog_manager.dialog_data.pop(PAYMENT_CACHE_KEY, None)

    if not plans:
        logger.warning(f"{user.log} No available subscription plans")
        await notifier.notify_user(user, i18n_key="ntf-subscription.plans-unavailable")
        return

    if not gateways:
        logger.warning(f"{user.log} No active payment gateways")
        await notifier.notify_user(user, i18n_key="ntf-subscription.gateways-unavailable")
        return

    current_subscription = await subscription_dao.get_current(user.id)

    if purchase_type == PurchaseType.RENEW:
        if await _resolve_renew_plan(
            user, dialog_manager, current_subscription, plans, match_plan, notifier, retort
        ):
            return

    if len(plans) == 1:
        logger.info(f"{user.log} Auto-selected single plan '{plans[0].id}'")
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plans[0])
        dialog_manager.dialog_data["only_single_plan"] = True

        if len(plans[0].durations) == 1:
            logger.info(f"{user.log} Auto-selected duration '{plans[0].durations[0].days}'")
            dialog_manager.dialog_data["selected_duration"] = plans[0].durations[0].days
            dialog_manager.dialog_data["only_single_duration"] = True

            if len(gateways) == 1:
                dialog_manager.dialog_data["selected_payment_method"] = gateways[0].type
                dialog_manager.dialog_data["only_single_payment_method"] = True

                # Single gateway may still be Platega with an in-bot method choice.
                routed, payment_method = await _resolve_platega_method(
                    dialog_manager,
                    plans[0],
                    plans[0].durations[0].days,
                    gateways[0].type,
                    payment_gateway_dao,
                    pricing_service,
                    user,
                )
                if routed:
                    return

                logger.info(f"{user.log} Auto-selected payment method '{gateways[0].type}'")
                payment_data = await _create_payment_and_get_data(
                    dialog_manager=dialog_manager,
                    plan=plans[0],
                    duration_days=plans[0].durations[0].days,
                    gateway_type=gateways[0].type,
                    retort=retort,
                    payment_gateway_dao=payment_gateway_dao,
                    notifier=notifier,
                    pricing_service=pricing_service,
                    create_payment=create_payment,
                    payment_method=payment_method,
                )

                if payment_data:
                    _save_payment_data(dialog_manager, payment_data)

                await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)
                return

            await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)
            return

        await dialog_manager.switch_to(state=Subscription.DURATION)
        return

    dialog_manager.dialog_data["only_single_plan"] = False
    dialog_manager.dialog_data["only_single_duration"] = False
    await dialog_manager.switch_to(state=Subscription.PLANS)


@inject
async def on_plan_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_plan: int,
    retort: FromDishka[Retort],
    plan_dao: FromDishka[PlanDao],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan = await plan_dao.get_by_id(plan_id=selected_plan)

    if not plan:
        logger.error(f"{user.log} Selected plan with id '{selected_plan}', but it was not found")
        await dialog_manager.start(state=Subscription.MAIN)
        return

    logger.info(f"{user.log} Selected plan '{plan.id}'")

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    dialog_manager.dialog_data.pop(PAYMENT_CACHE_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_METHOD_KEY, None)
    _clear_payment_state(dialog_manager)

    if len(plan.durations) == 1:
        logger.info(f"{user.log} Auto-selected single duration '{plan.durations[0].days}'")
        dialog_manager.dialog_data["only_single_duration"] = True
        await on_duration_select(callback, widget, dialog_manager, plan.durations[0].days)  # type:ignore[no-untyped-call]
        return

    dialog_manager.dialog_data["only_single_duration"] = False
    await dialog_manager.switch_to(state=Subscription.DURATION)


@inject
async def on_duration_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_duration: int,
    retort: FromDishka[Retort],
    settings_dao: FromDishka[SettingsDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
    pricing_service: FromDishka[PricingService],
    create_payment: FromDishka[CreatePayment],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Selected subscription duration '{selected_duration}' days")
    dialog_manager.dialog_data[CURRENT_DURATION_KEY] = selected_duration

    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        logger.error("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)
        return

    plan = retort.load(raw_plan, PlanDto)
    duration = plan.get_duration(selected_duration)
    if duration is None:
        logger.warning(f"{user.log} duration '{selected_duration}' missing (stale dialog data)")
        await dialog_manager.start(state=Subscription.MAIN)
        return
    settings = await settings_dao.get()
    gateways = await payment_gateway_dao.get_active()
    currency = settings.default_currency
    price = pricing_service.calculate(
        user,
        price=duration.get_price(currency),
        currency=currency,
    )
    dialog_manager.dialog_data["is_free"] = price.is_free

    if len(gateways) == 1 or price.is_free:
        selected_payment_method = gateways[0].type
        dialog_manager.dialog_data[CURRENT_METHOD_KEY] = selected_payment_method

        # Single gateway may still be Platega with an in-bot method choice.
        routed, payment_method = await _resolve_platega_method(
            dialog_manager,
            plan,
            selected_duration,
            selected_payment_method,
            payment_gateway_dao,
            pricing_service,
            user,
        )
        if routed:
            return

        purchase_type: PurchaseType = dialog_manager.dialog_data["purchase_type"]
        cache = _load_payment_data(dialog_manager)
        cache_key = _get_cache_key(
            selected_duration, selected_payment_method, purchase_type, payment_method
        )

        if cache_key in cache:
            logger.info(f"{user.log} Re-selected same duration and single gateway")
            _save_payment_data(dialog_manager, cache[cache_key])
            await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)
            return

        logger.info(f"{user.log} Auto-selected single gateway '{selected_payment_method}'")

        payment_data = await _create_payment_and_get_data(
            dialog_manager=dialog_manager,
            plan=plan,
            duration_days=selected_duration,
            gateway_type=selected_payment_method,
            retort=retort,
            payment_gateway_dao=payment_gateway_dao,
            notifier=notifier,
            pricing_service=pricing_service,
            create_payment=create_payment,
            payment_method=payment_method,
        )

        if payment_data:
            cache[cache_key] = payment_data
            _save_payment_data(dialog_manager, payment_data)
            await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)
            return

    dialog_manager.dialog_data.pop(CURRENT_METHOD_KEY, None)
    _clear_payment_state(dialog_manager)
    await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)


@inject
async def on_payment_method_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_payment_method: PaymentGatewayType,
    retort: FromDishka[Retort],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
    pricing_service: FromDishka[PricingService],
    create_payment: FromDishka[CreatePayment],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Selected payment method '{selected_payment_method}'")

    selected_duration = dialog_manager.dialog_data[CURRENT_DURATION_KEY]
    dialog_manager.dialog_data[CURRENT_METHOD_KEY] = selected_payment_method
    purchase_type: PurchaseType = dialog_manager.dialog_data["purchase_type"]

    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        logger.error("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)
        return

    plan = retort.load(raw_plan, PlanDto)

    routed, payment_method = await _resolve_platega_method(
        dialog_manager,
        plan,
        selected_duration,
        selected_payment_method,
        payment_gateway_dao,
        pricing_service,
        user,
    )
    if routed:
        return

    cache = _load_payment_data(dialog_manager)
    cache_key = _get_cache_key(
        selected_duration, selected_payment_method, purchase_type, payment_method
    )

    if cache_key in cache:
        logger.info(f"{user.log} Re-selected same method and duration")
        _save_payment_data(dialog_manager, cache[cache_key])
        await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)
        return

    logger.info(f"{user.log} New combination. Creating new payment")

    payment_data = await _create_payment_and_get_data(
        dialog_manager=dialog_manager,
        plan=plan,
        duration_days=selected_duration,
        gateway_type=selected_payment_method,
        retort=retort,
        payment_gateway_dao=payment_gateway_dao,
        notifier=notifier,
        pricing_service=pricing_service,
        create_payment=create_payment,
        payment_method=payment_method,
    )

    if payment_data:
        cache[cache_key] = payment_data
        _save_payment_data(dialog_manager, payment_data)

    await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)


@inject
async def on_platega_method_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_method: int,
    retort: FromDishka[Retort],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
    pricing_service: FromDishka[PricingService],
    create_payment: FromDishka[CreatePayment],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Selected Platega method '{selected_method}'")

    selected_duration = dialog_manager.dialog_data[CURRENT_DURATION_KEY]
    purchase_type: PurchaseType = dialog_manager.dialog_data["purchase_type"]
    gateway_type = PaymentGatewayType.PLATEGA  # the picker is only reached for Platega

    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)
    if not raw_plan:
        logger.error("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)
        return
    plan = retort.load(raw_plan, PlanDto)

    cache = _load_payment_data(dialog_manager)
    cache_key = _get_cache_key(selected_duration, gateway_type, purchase_type, selected_method)

    if cache_key in cache:
        logger.info(f"{user.log} Re-selected same Platega method")
        _save_payment_data(dialog_manager, cache[cache_key])
        await dialog_manager.switch_to(state=Subscription.PLATEGA_METHOD)
        return

    payment_data = await _create_payment_and_get_data(
        dialog_manager=dialog_manager,
        plan=plan,
        duration_days=selected_duration,
        gateway_type=gateway_type,
        retort=retort,
        payment_gateway_dao=payment_gateway_dao,
        notifier=notifier,
        pricing_service=pricing_service,
        create_payment=create_payment,
        payment_method=selected_method,
    )

    if payment_data:
        cache[cache_key] = payment_data
        _save_payment_data(dialog_manager, payment_data)

    await dialog_manager.switch_to(state=Subscription.PLATEGA_METHOD)


async def on_back_to_gateways(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    # Leaving the Platega method screen back to the gateway list: drop the pay-state so
    # the gateway list is shown fresh (not as a stale «Оплатить» screen).
    _clear_payment_state(dialog_manager)
    await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)


@inject
async def on_get_subscription(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    process_payment: FromDishka[ProcessPayment],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    payment_id = dialog_manager.dialog_data["payment_id"]
    gateway_type: PaymentGatewayType = dialog_manager.dialog_data[CURRENT_METHOD_KEY]
    logger.info(f"{user.log} Getted free subscription '{payment_id}'")
    await process_payment.system(
        ProcessPaymentDto(
            payment_id=payment_id,
            new_transaction_status=TransactionStatus.COMPLETED,
            gateway_type=gateway_type,
        ),
    )
