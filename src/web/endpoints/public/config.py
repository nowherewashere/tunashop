from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter

from src.application.common.dao import PlanDao
from src.core.config import AppConfig
from src.core.constants import T_ME
from src.core.enums import PlanAvailability
from src.web.schemas import PublicConfigResponse, SupportConfigResponse

router = APIRouter(tags=["Public - Config"])


@router.get("/config", response_model=PublicConfigResponse)
@inject
async def get_public_config(
    config: FromDishka[AppConfig],
    plan_dao: FromDishka[PlanDao],
) -> PublicConfigResponse:
    """Public, unauthenticated frontend config (Turnstile key, referral trial bonus)."""
    # The referred-friend trial length is data-driven: the active INVITED trial plan
    # (picked by GetAvailableTrial for referred users, ordered by order_index).
    referred_trial_days: int | None = None
    trials = await plan_dao.get_active_trial_plans()
    invited = sorted(
        (p for p in trials if p.availability == PlanAvailability.INVITED),
        key=lambda p: p.order_index,
    )
    if invited and invited[0].durations:
        referred_trial_days = invited[0].durations[0].days

    support_username = config.bot.support_username.get_secret_value()
    support = SupportConfigResponse(
        enabled=config.support.is_active,
        # Fallback contact (also the "open in Telegram" alternative when live chat is on).
        telegram_url=f"{T_ME}{support_username}" if support_username else None,
    )

    return PublicConfigResponse(
        turnstile_site_key=config.turnstile_site_key or None,
        referred_trial_days=referred_trial_days,
        support=support,
    )
