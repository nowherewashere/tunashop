from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, status

from src.application.common import BotService
from src.application.common.dao import ReferralDao, SettingsDao, SubscriptionDao
from src.core.config import AppConfig
from src.core.enums import SubscriptionStatus
from src.web.schemas import ReferralProgramResponse, ReferralRewardLevelResponse

from ._common import CurrentUser

router = APIRouter(prefix="/referral", tags=["Public - Referral"])


@router.get("/program", response_model=ReferralProgramResponse)
@inject
async def get_referral_program(
    user: CurrentUser,
    config: FromDishka[AppConfig],
    bot_service: FromDishka[BotService],
    settings_dao: FromDishka[SettingsDao],
    referral_dao: FromDishka[ReferralDao],
    subscription_dao: FromDishka[SubscriptionDao],
) -> ReferralProgramResponse:
    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is available only for users with verified email",
        )

    current_subscription = await subscription_dao.get_current(user.id)
    if not current_subscription or current_subscription.current_status != SubscriptionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is available only for users with active subscription",
        )

    settings = await settings_dao.get()

    if not settings.referral.enable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is disabled",
        )

    invited_count = await referral_dao.get_referrals_count(user.id)
    invited_with_payment_count = await referral_dao.get_referrals_with_payment_count(user.id)

    reward_levels = [
        ReferralRewardLevelResponse(level=level.value, value=value)
        for level, value in sorted(
            settings.referral.reward.config.items(),
            key=lambda item: item[0].value,
        )
        if level.value <= settings.referral.level.value
    ]

    bot_referral_url = await bot_service.get_referral_url(user.referral_code)
    site_base = config.referral_site_url.rstrip("/")
    site_referral_url = f"{site_base}/r/{user.referral_code}" if site_base else None

    return ReferralProgramResponse(
        enabled=settings.referral.enable,
        referral_code=user.referral_code,
        bot_referral_url=bot_referral_url,
        site_referral_url=site_referral_url,
        invited_count=invited_count,
        invited_with_payment_count=invited_with_payment_count,
        reward_type=settings.referral.reward.type.value,
        reward_strategy=settings.referral.reward.strategy.value,
        accrual_strategy=settings.referral.accrual_strategy.value,
        max_level=settings.referral.level.value,
        reward_levels=reward_levels,
    )
