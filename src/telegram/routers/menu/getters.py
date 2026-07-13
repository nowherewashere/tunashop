from datetime import timedelta
from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, Remnawave, TranslatorRunner
from src.application.common.dao import (
    PlanDao,
    ReferralLedgerDao,
    SettingsDao,
    SubscriptionDao,
    UserConnectionStateDao,
)
from src.application.dto import TelegramUserDto
from src.application.use_cases.misc.queries.menu import GetMenuData
from src.application.use_cases.referral.queries.summary import (
    GetReferralSummary,
    GetReferralSummaryDto,
)
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.config import AppConfig
from src.core.enums import Currency, PlanAvailability
from src.core.exceptions import MenuRenderError, PriceNotFoundError
from src.core.utils.i18n_helpers import (
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.core.utils.money import kop_to_rub, kop_to_stars
from src.core.utils.text import strip_leading_emoji
from src.core.utils.time import datetime_now, get_traffic_reset_delta
from src.infrastructure.database.models.referral_ledger import (
    PAYOUT_METHOD_STARS,
    PAYOUT_REQUESTED,
)
from src.telegram.utils import translate_or_literal


def _term_label(days: int) -> str:
    if days > 0 and days % 30 == 0:
        return f"{days // 30} мес"
    return f"{days} дн"

# Hub shows the "trial ending" face (coral accent + soft upsell, spec §7) once the
# trial has less than this left.
TRIAL_ENDING_THRESHOLD = timedelta(hours=4)


@inject
async def menu_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    get_menu_data: FromDishka[GetMenuData],
    settings_dao: FromDishka[SettingsDao],
    conn_state_dao: FromDishka[UserConnectionStateDao],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        menu_data = await get_menu_data(user)
        settings = await settings_dao.get()
        support_url = bot_service.get_support_url(text=i18n.get("message.help"))

        # connected_once drives the primary-button switch (Подключиться ↔ Открыть
        # инструкции, spec §4.1). Only consulted while the guided funnel is on, so
        # the read stays isolated behind the same flag.
        connected_once = (
            await conn_state_dao.is_connected_once(user.telegram_id)
            if settings.extra.onboarding_enabled
            else False
        )

        purchase_discount = user.purchase_discount or 0
        personal_discount = user.personal_discount or 0
        show_purchase_discount = purchase_discount > 0 and purchase_discount >= personal_discount
        show_personal_discount = personal_discount > 0 and not show_purchase_discount

        data: dict[str, Any] = {
            # user
            "telegram_id": user.telegram_id,
            "email": user.email,
            "name": user.name,
            "has_name": int(bool(user.name)),
            # Hub subscription header shows the active plan name (spec fix #3). Only
            # set for a real subscription below; empty ⇒ plain "Подписка:".
            "plan_name": "",
            "has_plan_name": 0,
            "personal_discount": personal_discount,
            "show_personal_discount": show_personal_discount,
            "purchase_discount": purchase_discount,
            "show_purchase_discount": show_purchase_discount,
            # ui / config
            "is_mini_app": config.bot.is_mini_app,
            "is_mini_app_reserve": config.bot.is_mini_app and settings.extra.mini_app_reserve,
            "onboarding_enabled": settings.extra.onboarding_enabled,
            "connected_once": connected_once,
            "trial_ending": 0,
            "support_url": support_url,
            "web_enabled": config.web_enabled,
            "web_cabinet_url": config.web_cabinet_url.strip(),
            # Show the cabinet button only when a URL is configured (empty ⇒ hidden,
            # and never a broken button with an empty href).
            "has_web_cabinet": bool(config.web_cabinet_url.strip()),
            # referral
            "referral_enabled": menu_data.is_referral_enabled,
            # defaults
            "has_subscription": False,
            "connectable": False,
            "trial_available": False,
            "trial_is_free": True,
            "trial_price": "",
            "has_device_limit": False,
            "is_trial": False,
            # True only for a paid (non-trial) subscription — drives whether the menu
            # "Подписка" button skips straight to buy (new/trial) or opens MAIN
            # (paid users, who choose between renew and change there).
            "has_active_subscription": False,
            # subscription-related (nullable)
            "status": None,
            "subscription_type": None,
            "traffic_limit": None,
            "device_limit": None,
            "expire_time": None,
            "reset_time": None,
            "connection_url": None,
            "subscription_url": None,
            "row_1_buttons": [b for b in menu_data.custom_buttons if b.index in (1, 2)],
            "row_2_buttons": [b for b in menu_data.custom_buttons if b.index in (3, 4)],
            "row_3_buttons": [b for b in menu_data.custom_buttons if b.index in (5, 6)],
        }

        if not menu_data.current_subscription:
            logger.debug(f"{user.log} has no active subscription")
            trial_plan = menu_data.available_trial
            trial_is_free = True
            trial_price_str = ""
            if trial_plan and menu_data.is_trial_available:
                currency = settings.default_currency
                raw_price = trial_plan.durations[0].get_price(currency)
                trial_is_free = raw_price == 0
                trial_price_str = (
                    f"{raw_price.normalize():f} {currency.symbol}" if not trial_is_free else ""
                )
            data["trial_available"] = menu_data.is_trial_available and menu_data.available_trial
            data["trial_is_free"] = trial_is_free
            data["trial_price"] = trial_price_str
            return data

        subscription = menu_data.current_subscription

        trial_ending = (
            subscription.is_trial
            and subscription.is_active
            and timedelta(0) < (subscription.expire_at - datetime_now()) <= TRIAL_ENDING_THRESHOLD
        )

        # The hub is the one surface that drops the plan's emoji (spec: emoji shows
        # everywhere the plan name renders EXCEPT the main menu). translate_or_literal
        # resolves a key-or-literal name; strip_leading_emoji removes the 🐟/🦈 prefix.
        plan_name = strip_leading_emoji(
            translate_or_literal(i18n, subscription.plan_snapshot.name)
        )

        data.update(
            {
                "has_subscription": True,
                "trial_ending": int(trial_ending),
                "is_trial": subscription.is_trial,
                "plan_name": plan_name,
                "has_plan_name": int(bool(plan_name)),
                "has_active_subscription": not subscription.is_trial,
                "traffic_strategy": subscription.traffic_limit_strategy,
                "status": subscription.current_status,
                "subscription_type": subscription.limit_type,
                "traffic_limit": i18n_format_traffic_limit(subscription.traffic_limit),
                "device_limit": i18n_format_device_limit(subscription.device_limit),
                "expire_time": i18n_format_expire_time(subscription.expire_at),
                "reset_time": i18n_format_expire_time(
                    get_traffic_reset_delta(
                        subscription.traffic_limit_strategy,
                        subscription.created_at,
                    )
                ),
                "connectable": subscription.is_active,
                "has_device_limit": (
                    subscription.has_devices_limit or subscription.device_limit == 0
                )
                if subscription.is_active
                else False,
                "connection_url": config.bot.mini_app_url
                if isinstance(config.bot.mini_app_url, str)
                else subscription.url,
                "subscription_url": subscription.url,
            }
        )
        logger.debug(f"Menu data for user {user.log}: {data}")
        return data

    except Exception as e:
        raise MenuRenderError(str(e)) from e


def get_platform_icon(i18n: TranslatorRunner, platform: str | None) -> str:
    known_platforms = {"ios", "android", "windows", "macos", "linux"}

    if platform and platform.lower() in known_platforms:
        return i18n.get(f"platform-icon.{platform.lower()}")
    return i18n.get("platform-icon.default")


@inject
async def devices_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    i18n: FromDishka[TranslatorRunner],
    subscription_dao: FromDishka[SubscriptionDao],
    remnawave: FromDishka[Remnawave],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)

    if not current_subscription:
        raise ValueError(f"Current subscription for user '{user.telegram_id}' not found")

    devices = await remnawave.get_devices(current_subscription.user_remna_id)

    formatted_devices = [
        {
            "index": index,
            "hwid": device.hwid,
            "platform": device.platform or False,
            "device_model": device.device_model or False,
            "user_agent": device.user_agent,
            "platform_icon": get_platform_icon(i18n, device.platform),
            "created_at": device.created_at.strftime("%d.%m.%Y"),
            "label": i18n.get(
                "btn-devices.item",
                platform_icon=get_platform_icon(i18n, device.platform),
                platform=device.platform or False,
                device_model=device.device_model or False,
                created_at=device.created_at.strftime("%d.%m.%Y"),
            ),
        }
        for index, device in enumerate(devices)
    ]

    dialog_manager.dialog_data["hwid_map"] = formatted_devices

    settings = await settings_dao.get()

    # device_limit == 0 means unlimited, so a limit is reached only when it is set
    # (>0) and every slot is taken. Drives the Add device ↔ Изменить подписку switch.
    at_device_limit = (
        current_subscription.device_limit != 0
        and len(devices) >= current_subscription.device_limit
    )

    return {
        "current_count": len(devices),
        "max_count": current_subscription.device_limit,
        "devices": formatted_devices,
        "devices_empty": len(devices) == 0,
        "has_devices": len(devices) > 0,
        "at_device_limit": int(at_device_limit),
        "device_single_enabled": int(settings.extra.device_single_reset.enabled),
        "device_all_enabled": int(settings.extra.device_all_reset.enabled),
        "link_reset_enabled": int(settings.extra.link_reset.enabled),
    }


@inject
async def device_confirm_delete_getter(
    dialog_manager: DialogManager,
    user: TelegramUserDto,
    **kwargs: Any,
) -> dict[str, Any]:
    return {
        "device_model": dialog_manager.dialog_data.get("selected_device_model", ""),
        "platform": dialog_manager.dialog_data.get("selected_platform", ""),
        "platform_icon": dialog_manager.dialog_data.get("selected_platform_icon", ""),
        "created_at": dialog_manager.dialog_data.get("selected_created_at", ""),
    }


async def _invited_trial_days(plan_dao: PlanDao) -> int | None:
    """Duration (days) of the active INVITED trial plan — what referred friends get.
    Same source as the site's /config referred_trial_days, so the two stay in sync.

    Not an aiogram-dialog getter and never dishka-injected — every caller
    (invite_getter / invite_about_getter) passes its own injected ``plan_dao``."""
    plans = await plan_dao.get_active_trial_plans()
    invited = sorted(
        (p for p in plans if p.availability == PlanAvailability.INVITED),
        key=lambda p: p.order_index,
    )
    if invited and invited[0].durations:
        return invited[0].durations[0].days
    return None


@inject
async def invite_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    bot_service: FromDishka[BotService],
    settings_dao: FromDishka[SettingsDao],
    get_referral_summary: FromDishka[GetReferralSummary],
    referral_ledger_dao: FromDishka[ReferralLedgerDao],
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    summary = await get_referral_summary.system(GetReferralSummaryDto(user.id))
    referral_url = await bot_service.get_referral_url(user.referral_code)

    # Second (website) referral link, spec §4.7 — shown only when configured.
    site_base = config.referral_site_url.strip().rstrip("/")
    site_referral_url = f"{site_base}/r/{user.referral_code}" if site_base else ""

    # Open-payout receipt (tofix item 11): show the amount, destination and payout day
    # under the "заявка в обработке" note, and let the user edit a crypto wallet while
    # the payout is still 'requested' (before an operator/batch takes it into work).
    open_payout = await referral_ledger_dao.get_open_payout(user.id)
    payout_fields: dict[str, Any] = {
        "payout_method": "crypto",
        "payout_amount": "0",
        "payout_asset": config.payout.crypto_asset,
        "payout_network": config.payout.crypto_network,
        "payout_wallet": "",
        "payout_stars": 0,
        "payout_editable": 0,
    }
    if open_payout:
        is_stars = open_payout.method == PAYOUT_METHOD_STARS
        payout_fields.update(
            {
                "payout_method": "stars" if is_stars else "crypto",
                "payout_amount": kop_to_rub(open_payout.amount_kop),
                "payout_asset": open_payout.crypto_asset or config.payout.crypto_asset,
                "payout_network": open_payout.crypto_network or config.payout.crypto_network,
                # Full wallet (not masked) so the user can double-check the exact address.
                "payout_wallet": open_payout.crypto_wallet or "",
                "payout_stars": open_payout.stars_amount or 0,
                "payout_editable": int(
                    not is_stars and open_payout.status == PAYOUT_REQUESTED
                ),
            }
        )

    trial_days = (await _invited_trial_days(plan_dao)) or 0
    return {
        **payout_fields,
        "trial_days": trial_days,
        "rate": config.referral.rate_bp // 100,
        # Stats block (spec §8.1) — real money now, all in ₽ (kopecks derived).
        "referrals": summary.invited,
        "payments": summary.paying,
        "balance": kop_to_rub(summary.balance_kop),
        "withdrawn": kop_to_rub(summary.withdrawn_kop),
        "spent_on_vpn": kop_to_rub(summary.spent_kop),
        "currency": "₽",
        # Crypto payout floor, shown on the "Вывести" button so the threshold is upfront.
        "withdraw_min": kop_to_rub(config.referral.payout_min_kop),
        "referral_url": referral_url,
        "site_referral_url": site_referral_url,
        "has_site_link": int(bool(site_referral_url)),
        "referral_reset_enabled": int(settings.extra.referral_reset.enabled),
        # The action buttons are always offered (discoverability); each flow explains
        # when there is nothing to do yet. They only hide while a payout is open, since
        # that locks both withdraw and pay-with-balance (spec §3.3) — the screen then
        # shows a "заявка в обработке" note so the still-shown balance isn't confusing.
        "has_open_payout": int(summary.has_open_payout),
    }


@inject
async def invite_withdraw_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    get_referral_summary: FromDishka[GetReferralSummary],
    **kwargs: Any,
) -> dict[str, Any]:
    summary = await get_referral_summary.system(GetReferralSummaryDto(user.id))
    return {
        "balance": kop_to_rub(summary.balance_kop),
        "currency": "₽",
        "crypto_asset": config.payout.crypto_asset,
        "crypto_network": config.payout.crypto_network,
    }


@inject
async def invite_withdraw_edit_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    get_referral_summary: FromDishka[GetReferralSummary],
    referral_ledger_dao: FromDishka[ReferralLedgerDao],
    **kwargs: Any,
) -> dict[str, Any]:
    # Change-address screen: show the current full wallet so the user can confirm
    # they're editing the right request.
    summary = await get_referral_summary.system(GetReferralSummaryDto(user.id))
    open_payout = await referral_ledger_dao.get_open_payout(user.id)
    current_wallet = (
        open_payout.crypto_wallet
        if open_payout and open_payout.crypto_wallet
        else "—"
    )
    return {
        "balance": kop_to_rub(summary.balance_kop),
        "currency": "₽",
        "crypto_asset": config.payout.crypto_asset,
        "crypto_network": config.payout.crypto_network,
        "current_wallet": current_wallet,
    }


@inject
async def invite_withdraw_method_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    get_referral_summary: FromDishka[GetReferralSummary],
    **kwargs: Any,
) -> dict[str, Any]:
    # Payout method picker (spec §8.3): crypto (real cash-out, ≥ crypto min, Monday
    # batch) vs Telegram Stars (in-ecosystem, ≥ stars min, needs a linked Telegram).
    summary = await get_referral_summary.system(GetReferralSummaryDto(user.id))
    balance_kop = summary.balance_kop
    rate = config.stars.rub_rate
    stars = kop_to_stars(balance_kop, rate)
    return {
        "balance": kop_to_rub(balance_kop),
        "currency": "₽",
        "crypto_asset": config.payout.crypto_asset,
        "crypto_network": config.payout.crypto_network,
        "crypto_min": kop_to_rub(config.referral.payout_min_kop),
        "stars": stars,
        "stars_rub": kop_to_rub(stars * rate),
        "stars_min": kop_to_rub(config.stars.min_kop),
        "has_telegram": int(user.telegram_id is not None),
    }


@inject
async def invite_withdraw_stars_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    get_referral_summary: FromDishka[GetReferralSummary],
    **kwargs: Any,
) -> dict[str, Any]:
    summary = await get_referral_summary.system(GetReferralSummaryDto(user.id))
    rate = config.stars.rub_rate
    stars = kop_to_stars(summary.balance_kop, rate)
    return {
        "balance": kop_to_rub(summary.balance_kop),
        "currency": "₽",
        "stars": stars,
        # The RUB value actually paid out (whole Stars × rate) — a sub-Star remainder
        # stays on the balance, so this can be a touch below the shown balance.
        "stars_rub": kop_to_rub(stars * rate),
    }


@inject
async def invite_pay_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    i18n: FromDishka[TranslatorRunner],
    get_available_plans: FromDishka[GetAvailablePlans],
    get_referral_summary: FromDishka[GetReferralSummary],
    **kwargs: Any,
) -> dict[str, Any]:
    summary = await get_referral_summary.system(GetReferralSummaryDto(user.id))
    plans = await get_available_plans.system(user)

    # Flat list of affordable plan × duration options (full-cover only, so we hide
    # anything the balance can't fully pay). The item id carries "plan_id:days".
    items: list[dict[str, Any]] = []
    for plan in plans:
        if plan.is_trial:
            continue
        name = translate_or_literal(i18n, plan.name)
        for duration in sorted(plan.durations, key=lambda d: d.days):
            try:
                price = duration.get_price(Currency.RUB)
            except PriceNotFoundError:
                continue
            price_kop = int(price * 100)
            if price_kop <= 0 or summary.balance_kop < price_kop:
                continue
            items.append(
                {
                    "id": f"{plan.id}:{duration.days}",
                    "label": f"{name} · {_term_label(duration.days)} · {int(price)} ₽",
                }
            )

    return {
        "balance": kop_to_rub(summary.balance_kop),
        "currency": "₽",
        "pay_items": items,
        "has_items": int(bool(items)),
    }


@inject
async def invite_about_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    # Money model (spec §1): rate% recurring, crypto payout from the min, or pay-VPN.
    return {
        "rate": config.referral.rate_bp // 100,
        "min": kop_to_rub(config.referral.payout_min_kop),
        "trial_days": (await _invited_trial_days(plan_dao)) or 0,
    }
