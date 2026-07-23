from typing import Optional
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Request, Response, status
from loguru import logger
from pydantic import BaseModel, Field

from src.application.common import EventPublisher
from src.application.common.dao import RateLimiter
from src.application.events.metrics import FunnelStepEvent
from src.core.config import AppConfig
from src.core.metrics import FUNNEL_UI_STEPS, FunnelStep, MetricSource
from src.web.endpoints.public._common import get_client_ip

router = APIRouter(prefix="/events", tags=["Public - Metrics"])

# Abuse guard for the open (pre-auth) write endpoint: generous, per-IP, fixed window.
_FUNNEL_RATE_LIMIT = 120
_FUNNEL_RATE_WINDOW_SECONDS = 60
# Absolute backstop across all callers. Per-IP attribution is only as good as the
# proxy chain (src/core/utils/net.py); this endpoint is unauthenticated, uncaptcha'd
# and writes a row per accepted call, so a ceiling that holds even when attribution
# fails is what actually bounds the damage. ~50 events/s sits far above realistic
# onboarding traffic — dropping telemetry above it is acceptable by the
# fire-and-forget contract below.
_FUNNEL_GLOBAL_RATE_LIMIT = 3000
_PLATFORM_MAX_LEN = 32


class FunnelStepRequest(BaseModel):
    step: str = Field(..., max_length=48)
    platform: Optional[str] = Field(default=None, max_length=_PLATFORM_MAX_LEN)
    # remnawave_uuid — the SPA sends it only after the subscription is known; the
    # early funnel steps (start/device) are anonymous and leave it null.
    user_ref: Optional[str] = Field(default=None, max_length=64)


@router.post("/funnel", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def track_funnel_step(
    payload: FunnelStepRequest,
    request: Request,
    event_publisher: FromDishka[EventPublisher],
    rate_limiter: FromDishka[RateLimiter],
    config: FromDishka[AppConfig],
) -> Response:
    """Record one onboarding funnel step from the static site (metrics spec §5).

    The site has no DB/server, so it POSTs each UI step here and the bot backend
    writes the ``funnel_step`` row — using the SAME ``FunnelStepEvent`` the bot
    publishes, so there is one write path and the funnels stay comparable across
    surfaces. Fire-and-forget by contract: this ALWAYS returns 204 and never blocks
    or errors the user's page — bad input, rate-limit, or a publish hiccup are all
    swallowed.
    """
    no_content = Response(status_code=status.HTTP_204_NO_CONTENT)

    # Only the client-emitted UI steps are accepted; first_connect / trial_converted
    # are server-detected business events (spec §4/§5) and must not be spoofable.
    if payload.step not in FUNNEL_UI_STEPS:
        return no_content

    ip = get_client_ip(request, config)
    try:
        # Per-IP first, so one noisy source is stopped without eating the shared
        # budget that protects everyone else.
        within_limit = await rate_limiter.hit(
            "funnel_metrics",
            ip,
            limit=_FUNNEL_RATE_LIMIT,
            window_seconds=_FUNNEL_RATE_WINDOW_SECONDS,
        )
        if not within_limit:
            return no_content

        within_global_limit = await rate_limiter.hit(
            "funnel_metrics_global",
            "all",
            limit=_FUNNEL_GLOBAL_RATE_LIMIT,
            window_seconds=_FUNNEL_RATE_WINDOW_SECONDS,
        )
        if not within_global_limit:
            return no_content

        await event_publisher.publish(
            FunnelStepEvent(
                step=FunnelStep(payload.step),
                source=MetricSource.SITE,
                platform=payload.platform,
                user_ref=_clean_user_ref(payload.user_ref),
            )
        )
    except Exception as error:
        # Telemetry must never surface to the user (spec §2, §7).
        logger.warning(f"funnel step '{payload.step}' from site dropped: {error}")

    return no_content


def _clean_user_ref(user_ref: Optional[str]) -> Optional[str]:
    """Accept a ``user_ref`` only if it is a real UUID — keeps the append-only store
    from being polluted with arbitrary keys from an open endpoint."""
    if not user_ref:
        return None
    try:
        return str(UUID(user_ref))
    except (ValueError, AttributeError):
        return None
