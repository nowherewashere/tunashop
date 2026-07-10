"""Bot-side onboarding funnel emits (metrics spec §5).

The bot publishes the same ``FunnelStepEvent`` the site posts, so the funnel is
comparable across surfaces. ``MetricsEventListener`` resolves the ``remnawave_uuid``
from ``telegram_id`` and writes the row. Emitting is fire-and-forget: a telemetry
hiccup must never break the onboarding dialog.
"""

from typing import Optional

from loguru import logger

from src.application.common import EventPublisher
from src.application.events.metrics import FunnelStepEvent
from src.core.metrics import FunnelStep, MetricSource


async def emit_funnel_step(
    publisher: EventPublisher,
    step: FunnelStep,
    *,
    telegram_id: Optional[int] = None,
    platform: Optional[str] = None,
) -> None:
    try:
        await publisher.publish(
            FunnelStepEvent(
                step=step,
                source=MetricSource.BOT,
                platform=platform,
                telegram_id=telegram_id,
            )
        )
    except Exception as error:  # pragma: no cover - telemetry must be invisible
        logger.warning(f"bot funnel step '{step}' dropped: {error}")
