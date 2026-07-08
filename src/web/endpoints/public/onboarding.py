from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter

from src.core.config import AppConfig
from src.web.schemas import (
    OnboardingConfigResponse,
    OnboardingStoreLinks,
    OnboardingTvConfig,
    OnboardingTvFaq,
)

router = APIRouter(prefix="/onboarding", tags=["Public - Onboarding"])


@router.get("/config", response_model=OnboardingConfigResponse)
@inject
async def get_onboarding_config(
    config: FromDishka[AppConfig],
) -> OnboardingConfigResponse:
    """Canonical Happ install links (single source: OnboardingConfig, shared with the bot).

    Public and unauthenticated — these are the same public download/import URLs the bot's
    onboarding funnel uses, so the website's install screens never drift from the bot.
    """
    ob = config.onboarding
    return OnboardingConfigResponse(
        happ_import_template=ob.happ_import_template,
        refresh_video_url=ob.refresh_video_url or None,
        store_links=OnboardingStoreLinks(
            ios=ob.happ_link_ios,
            android=ob.happ_link_android,
            windows=ob.happ_link_windows,
            mac=ob.happ_link_mac,
            linux=ob.happ_link_linux,
        ),
        store_link_ios_ru=ob.happ_link_ios_ru,
        tv=OnboardingTvConfig(
            web_import_url=ob.tv_web_import_url,
            faq=OnboardingTvFaq(
                apple_tv=ob.happ_faq_apple_tv,
                android_tv=ob.happ_faq_android_tv,
            ),
        ),
    )
