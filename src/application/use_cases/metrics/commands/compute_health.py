from datetime import timedelta

from loguru import logger

from src.application.common import Interactor, Notifier
from src.application.common.dao import EventsDao
from src.application.dto import MessagePayloadDto, UserDto
from src.application.dto.metrics import HealthRow
from src.core.enums import SystemNotificationType
from src.core.metrics import (
    HEALTH_MIN_SAMPLES,
    HEALTH_SUCCESS_THRESHOLD,
    HEALTH_WINDOW_MINUTES,
)
from src.core.utils.time import datetime_now

# Single i18n key lives in assets/translations/ru/metrics.ftl (a new file, so it
# never collides with the shared events.ftl).
_ALERT_KEY = "event-metrics-health-alert"


class ComputeNodeHealth(Interactor[None, list[HealthRow]]):
    """Health rollup every 5–15 min + the one threshold alert (metrics spec §6.5, §8).

    Rolls up probe success per (node × protocol × operator) over the recent window
    and fires exactly one alert to the ops chat when a slice drops below the
    threshold with enough samples to be meaningful — "one threshold = one alert, no
    anomaly engine" (§6.5). Ties into the reactive playbook: detect → switch
    protocol / push "обновите конфиг".
    """

    required_permission = None

    def __init__(self, events_dao: EventsDao, notifier: Notifier) -> None:
        self.events_dao = events_dao
        self.notifier = notifier

    async def _execute(self, actor: UserDto, data: None) -> list[HealthRow]:
        since = datetime_now() - timedelta(minutes=HEALTH_WINDOW_MINUTES)
        rows = await self.events_dao.node_protocol_health(since=since)

        breaches = [
            row
            for row in rows
            if row.total >= HEALTH_MIN_SAMPLES and row.success_rate < HEALTH_SUCCESS_THRESHOLD
        ]
        logger.info(
            f"[metrics] node health: {len(rows)} slices, {len(breaches)} below "
            f"{HEALTH_SUCCESS_THRESHOLD:.0%} over {HEALTH_WINDOW_MINUTES}m"
        )
        if breaches:
            await self._alert(breaches)
        return rows

    async def _alert(self, breaches: list[HealthRow]) -> None:
        detail = "\n".join(
            f"• {row.node_id} / {row.protocol or 'node'}"
            f"{' / ' + row.operator if row.operator else ''}: "
            f"{row.success}/{row.total} = {row.success_rate:.0%}"
            for row in breaches
        )
        try:
            await self.notifier.notify_system(
                MessagePayloadDto(
                    i18n_key=_ALERT_KEY,
                    i18n_kwargs={
                        "detail": detail,
                        "window": HEALTH_WINDOW_MINUTES,
                        "threshold": int(HEALTH_SUCCESS_THRESHOLD * 100),
                    },
                    delete_after=None,
                ),
                notification_type=SystemNotificationType.NODE_STATUS_CHANGED,
            )
        except Exception as error:
            logger.warning(f"[metrics] health alert delivery failed: {error}")
