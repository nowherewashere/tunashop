from decimal import Decimal

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from redis.asyncio import Redis

from src.application.common.dao import PlanDao, TrafficPoolDao
from src.core.config import AppConfig
from src.core.constants import (
    PUBLIC_LANDING_PLANS_CACHE_KEY,
    PUBLIC_LANDING_PLANS_CACHE_TTL_SECONDS,
)
from src.core.enums import Currency, PlanAvailability
from src.web.schemas import (
    PublicPlanLandingListResponse,
    PublicPlanLandingResponse,
    PublicPlanPoolResponse,
)

from ._common import _normalize_decimal_str

router = APIRouter(tags=["Public - Plans"])

_CACHE_KEY = PUBLIC_LANDING_PLANS_CACHE_KEY


@router.get("/plans/public", response_model=PublicPlanLandingListResponse)
@inject
async def get_public_landing_plans(
    plan_dao: FromDishka[PlanDao],
    traffic_pool_dao: FromDishka[TrafficPoolDao],
    config: FromDishka[AppConfig],
    redis: FromDishka[Redis],
) -> PublicPlanLandingListResponse:
    cached = await redis.get(_CACHE_KEY)
    if cached is not None:
        return PublicPlanLandingListResponse.model_validate_json(cached)

    plans = await plan_dao.filter_by_availability(PlanAvailability.ALL)
    # Pool names live on the pool row, not on the plan, so a rename reflects on every
    # card at once. Empty while the feature is off ⇒ the field stays None.
    pools_by_id = (
        {pool.id: pool for pool in await traffic_pool_dao.get_all()}
        if config.traffic_pools.enabled
        else {}
    )

    result: list[PublicPlanLandingResponse] = []
    for plan in plans:
        if not plan.is_active or plan.is_trial or not plan.public_code:
            continue

        rub_duration_candidates: list[tuple[int, Decimal]] = []
        for duration in plan.durations:
            if duration.days <= 0:
                continue

            rub_price = next((p.price for p in duration.prices if p.currency == Currency.RUB), None)
            if rub_price is not None:
                rub_duration_candidates.append((duration.days, rub_price))

        if not rub_duration_candidates:
            continue

        max_duration_days, max_duration_price = max(
            rub_duration_candidates,
            key=lambda item: item[0],
        )
        monthly_from = (max_duration_price * Decimal(30)) / Decimal(max_duration_days)

        result.append(
            PublicPlanLandingResponse(
                public_code=plan.public_code,
                name=plan.name,
                description=plan.description,
                locations=plan.locations,
                traffic_limit=plan.traffic_limit,
                device_limit=plan.device_limit,
                monthly_from_rub=_normalize_decimal_str(monthly_from),
                max_duration_days=max_duration_days,
                max_duration_price_rub=_normalize_decimal_str(max_duration_price),
                pools=[
                    PublicPlanPoolResponse(
                        pool_id=quota.pool_id,
                        name=pools_by_id[quota.pool_id].name,
                        quota_bytes=quota.quota_bytes,
                        reset_strategy=quota.reset_strategy.value,
                    )
                    for quota in plan.pool_quotas
                    if quota.pool_id in pools_by_id and quota.quota_gb > 0
                ]
                or None,
            )
        )

    payload = PublicPlanLandingListResponse(plans=result)
    await redis.setex(_CACHE_KEY, PUBLIC_LANDING_PLANS_CACHE_TTL_SECONDS, payload.model_dump_json())
    return payload
