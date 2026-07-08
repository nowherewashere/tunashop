from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter

from src.core.config import AppConfig
from src.web.schemas import PublicConfigResponse

router = APIRouter(tags=["Public - Config"])


@router.get("/config", response_model=PublicConfigResponse)
@inject
async def get_public_config(config: FromDishka[AppConfig]) -> PublicConfigResponse:
    """Public, unauthenticated frontend config (e.g. the Turnstile site key)."""
    return PublicConfigResponse(
        turnstile_site_key=config.turnstile_site_key or None,
        chatwoot_base_url=config.chatwoot_base_url or None,
        chatwoot_website_token=config.chatwoot_website_token or None,
    )
