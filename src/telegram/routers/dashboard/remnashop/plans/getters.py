from decimal import Decimal
from typing import Any, Optional, Union

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from remnapy.enums.users import TrafficLimitStrategy

from src.application.common import BotService, Remnawave, TranslatorRunner
from src.application.common.dao import PlanDao
from src.application.dto import PlanDto, PlanDurationDto, PlanPriceDto, TelegramUserDto
from src.application.services.traffic_pools import TrafficPoolAccessService
from src.application.use_cases.traffic_pool import GetTrafficPools
from src.core.constants import USER_KEY
from src.core.enums import Currency, PlanAvailability, PlanType
from src.telegram.utils import plan_pool_lines


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    plans: list[PlanDto] = await plan_dao.get_all()

    formatted_plans = [
        {
            "id": plan.id,
            "name": plan.name,
            "is_active": plan.is_active,
        }
        for plan in plans
    ]

    return {
        "has_plans": bool(plans),
        "plans": formatted_plans,
    }


@inject
async def export_getter(
    dialog_manager: DialogManager,
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    plans: list[PlanDto] = await plan_dao.get_all()
    selected_plans = dialog_manager.dialog_data.get("selected_plans", [])

    formatted_plans = [
        {
            "id": plan.id,
            "name": plan.name,
            "selected": plan.id in selected_plans,
        }
        for plan in plans
    ]

    return {
        "plans": formatted_plans,
    }


@inject
async def configurator_getter(
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    pool_access: FromDishka[TrafficPoolAccessService],
    get_pools: FromDishka[GetTrafficPools],
    **kwargs: Any,
) -> dict[str, Any]:
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if raw_plan is None:
        plan = PlanDto(
            name=i18n.get("plan-default-name"),
            durations=[
                PlanDurationDto(
                    days=7,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(0.5)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(30)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(50)),
                    ],
                ),
                PlanDurationDto(
                    days=30,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(1)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(60)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(100)),
                    ],
                ),
                PlanDurationDto(
                    days=365,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(10)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(600)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(1000)),
                    ],
                ),
                PlanDurationDto(
                    days=0,
                    prices=[
                        PlanPriceDto(currency=Currency.USD, price=Decimal(100)),
                        PlanPriceDto(currency=Currency.XTR, price=Decimal(6000)),
                        PlanPriceDto(currency=Currency.RUB, price=Decimal(10000)),
                    ],
                ),
            ],
        )
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    else:
        plan = retort.load(raw_plan, PlanDto)

    # Gated on the feature flag, not just on the plan having quotas: with pools off
    # nothing meters or enforces them, and a card advertising an inert quota reads as
    # a promise. The «Квоты по пулам» screen still shows and edits them either way,
    # so a quota configured ahead of the rollout is never hidden from its own editor.
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    pools_by_id = (
        {pool.id: pool for pool in await get_pools(user)} if pool_access.is_enabled else {}
    )

    helpers = {
        "name": plan.name,
        "is_edit": dialog_manager.dialog_data.get("is_edit", False),
        "is_unlimited_traffic": plan.is_unlimited_traffic,
        "is_unlimited_devices": plan.is_unlimited_devices,
        "pools_line": plan_pool_lines(i18n, plan.pool_quotas, pools_by_id),
        "plan_type": plan.type,
        "availability_type": plan.availability,
        "plan_url": f"{await bot_service.get_plan_url(plan.public_code)}"
        if plan.public_code
        else False,
    }

    data: dict = retort.dump(plan)
    data.update(helpers)
    return data


@inject
async def name_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {"name": plan.name}


@inject
async def description_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {"description": plan.description}


@inject
async def tag_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {"tag": plan.tag}


@inject
async def locations_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {"locations": plan.locations}


@inject
async def type_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    return {
        "is_trial": plan.is_trial,
        "types": list(PlanType),
    }


async def availability_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"availability": list(PlanAvailability)}


@inject
async def traffic_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    strategys = [
        {
            "strategy": strategy,
            "selected": strategy.name == plan.traffic_limit_strategy,
        }
        for strategy in TrafficLimitStrategy
    ]

    return {"strategys": strategys}


@inject
async def durations_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    durations = [retort.dump(duration) for duration in plan.durations]

    return {
        "deletable": len(durations) > 1,
        "durations": durations,
    }


def get_prices_for_duration(
    durations: list[PlanDurationDto],
    target_days: int,
) -> Optional[list[PlanPriceDto]]:
    for duration in durations:
        if duration.days == target_days:
            return duration.prices
    return []


@inject
async def prices_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    prices = get_prices_for_duration(plan.durations, selected_duration)
    prices_data = [retort.dump(price) for price in prices] if prices else []

    return {
        "duration": selected_duration,
        "prices": prices_data,
    }


async def price_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    selected_duration = dialog_manager.dialog_data.get("selected_duration")
    selected_currency = dialog_manager.dialog_data.get("selected_currency")
    return {
        "duration": selected_duration,
        "currency": selected_currency,
    }


@inject
async def allowed_users_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    combined: list[str] = [f"tg:{tg_id}" for tg_id in plan.allowed_telegram_ids]
    combined += [f"em:{email}" for email in plan.allowed_emails]
    return {"allowed_users": combined}


@inject
async def squads_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    internal_dict = {s.uuid: s.name for s in await remnawave.get_internal_squads()}

    if not plan.internal_squads:
        internal_squads_data: Union[str, bool] = False
    else:
        internal_squads_data = ", ".join(
            internal_dict.get(squad, str(squad)) for squad in plan.internal_squads
        )

    external_dict = {s.uuid: s.name for s in await remnawave.get_external_squads()}
    external_squad_data = external_dict.get(plan.external_squad) if plan.external_squad else False

    return {
        "internal_squads": internal_squads_data,
        "external_squad": external_squad_data,
    }


@inject
async def internal_squads_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    squads = [
        {
            "uuid": squad.uuid,
            "name": squad.name,
            "selected": squad.uuid in plan.internal_squads,
        }
        for squad in await remnawave.get_internal_squads()
    ]

    return {
        "squads": squads,
    }


@inject
async def pool_quotas_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    get_pools: FromDishka[GetTrafficPools],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    quotas = {quota.pool_id: quota for quota in plan.pool_quotas}
    pools = [pool for pool in await get_pools(user) if pool.is_active]

    return {
        "has_pools": bool(pools),
        "pools": [
            {
                "id": pool.id,
                "name": pool.name,
                "quota_gb": quotas[pool.id].quota_gb if pool.id in quotas else 0,
                # A quota can only be enforced by withdrawing the pool's squad, so on a
                # plan that never grants it there is nothing to meter. Flagged here so
                # the admin sees why the row is inert instead of losing it on save.
                "is_granted": pool.internal_squad_uuid in plan.internal_squads,
            }
            for pool in pools
        ],
    }


@inject
async def pool_quota_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    get_pools: FromDishka[GetTrafficPools],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    pool_id = dialog_manager.dialog_data.get("selected_pool")

    pool = next((p for p in await get_pools(user) if p.id == pool_id), None)
    quota = next((q for q in plan.pool_quotas if q.pool_id == pool_id), None)

    return {
        "pool_name": pool.name if pool else str(pool_id),
        "quota_gb": quota.quota_gb if quota else 0,
        # Named to match the `traffic-strategy` term's argument, which this screen
        # reuses so the wording is identical to the plan's own traffic strategy.
        "strategy_type": (quota.reset_strategy if quota else TrafficLimitStrategy.MONTH),
    }


@inject
async def pool_strategy_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)
    pool_id = dialog_manager.dialog_data.get("selected_pool")
    quota = next((q for q in plan.pool_quotas if q.pool_id == pool_id), None)
    current = quota.reset_strategy if quota else TrafficLimitStrategy.MONTH

    return {
        "strategys": [
            {"strategy": strategy, "selected": strategy == current}
            for strategy in TrafficLimitStrategy
        ],
    }


@inject
async def external_squads_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    plan = retort.load(dialog_manager.dialog_data[PlanDto.__name__], PlanDto)

    squads = [
        {
            "uuid": squad.uuid,
            "name": squad.name,
            "selected": squad.uuid == plan.external_squad,
        }
        for squad in await remnawave.get_external_squads()
    ]

    return {
        "squads": squads,
    }
