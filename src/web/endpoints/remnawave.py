import json
from typing import Any, cast

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Request, Response, status
from loguru import logger
from remnapy.controllers import WebhookUtility
from remnapy.models.webhook import (
    NodeDto,
    TorrentBlockerReportDto,
    UserDto,
    UserHwidDeviceEventDto,
)

from src.application.common import EventPublisher
from src.application.events import ErrorEvent
from src.application.services import RemnaWebhookService
from src.core.config import AppConfig
from src.core.constants import API_V1, REMNAWAVE_WEBHOOK_PATH
from src.core.utils.log_throttle import LogThrottle, log_throttled

router = APIRouter(prefix=API_V1, include_in_schema=False)

# This endpoint is reachable by anyone, and every rejection below used to write its
# own line — a traceback, in the parse case. Collapse repeats so a junk-POST flood
# cannot drive disk writes or bury the real events.
_REJECTION_LOG = LogThrottle()


def _adapt_hwid_device_payload(body: dict[str, Any]) -> None:
    """Adapt Remnawave's `user_hwid_devices` payload to the pinned remnapy schema.

    The panel emits the device object with `userId` (internal numeric id) and no
    `userUuid`, while remnapy's `HwidUserDeviceDto` requires `userUuid: UUID`. We
    backfill it from the sibling `user.uuid` so parsing does not fail. This is an
    anti-corruption shim for a schema drift between the panel and the pinned SDK;
    it can be removed once remnapy's model matches the panel.
    """
    event = body.get("event", "")
    if not event.startswith("user_hwid_devices."):
        return

    data = body.get("data")
    if not isinstance(data, dict):
        return

    device = data.get("hwidUserDevice")
    user = data.get("user")
    if not isinstance(device, dict) or not isinstance(user, dict):
        return

    if not device.get("userUuid") and user.get("uuid"):
        device["userUuid"] = user["uuid"]


async def _process_remnawave_webhook(
    request: Request,
    config: AppConfig,
    remna_webhook_service: RemnaWebhookService,
    event_publisher: EventPublisher,
) -> Response:
    try:
        raw_body = await request.body()
        raw_str = raw_body.decode("utf-8")
        logger.debug(f"Received Remnawave webhook raw body: '{raw_str[:500]}'")

        # Validate the signature against the *original* body, then adapt the payload
        # before parsing so a schema drift in one scope cannot 401 the whole webhook.
        if not WebhookUtility.validate_webhook_with_headers(
            body=raw_str,
            headers=dict(request.headers),
            webhook_secret=config.remnawave.webhook_secret.get_secret_value(),
        ):
            log_throttled(
                _REJECTION_LOG, "bad-signature", "WARNING", "Webhook signature validation failed"
            )
            raise HTTPException(status_code=401)

        body = json.loads(raw_str)
        _adapt_hwid_device_payload(body)

        payload = WebhookUtility.parse_webhook(
            body=body,
            headers=dict(request.headers),
            webhook_secret=config.remnawave.webhook_secret.get_secret_value(),
            validate=False,
        )
    except HTTPException:
        raise
    except Exception as e:
        # Kept at exception level so a genuine bug still yields a traceback, but
        # throttled: a malformed body is client-controlled and would otherwise print
        # a full traceback per request.
        log_throttled(
            _REJECTION_LOG,
            "validation-error",
            "ERROR",
            f"Webhook validation failed: '{e}'",
            exception=True,
        )
        raise HTTPException(status_code=401)

    if not payload:
        log_throttled(
            _REJECTION_LOG, "empty-payload", "WARNING", "Payload is empty after validation"
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        if WebhookUtility.is_user_event(payload.event):
            user = cast(UserDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_user_event(payload.event, user)

        elif WebhookUtility.is_user_hwid_devices_event(payload.event):
            event = cast(UserHwidDeviceEventDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_device_event(
                payload.event,
                event.user,
                event.hwid_user_device,
            )

        elif WebhookUtility.is_node_event(payload.event):
            node = cast(NodeDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_node_event(payload.event, node)

        elif WebhookUtility.is_torrent_blocker_event(payload.event):
            report = cast(TorrentBlockerReportDto, WebhookUtility.get_typed_data(payload))
            await remna_webhook_service.handle_torrent_blocker_event(report)

        else:
            logger.warning(f"Unhandled Remnawave event type '{payload.event}'")

    except Exception as e:
        logger.exception(f"Failed to process Remnawave webhook due to '{e}'")
        error_event = ErrorEvent(**config.build.data, exception=e)
        await event_publisher.publish(error_event)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response(status_code=status.HTTP_200_OK)


@router.post(REMNAWAVE_WEBHOOK_PATH)
@inject
async def remnawave_webhook(
    request: Request,
    config: FromDishka[AppConfig],
    remna_webhook_service: FromDishka[RemnaWebhookService],
    event_publisher: FromDishka[EventPublisher],
) -> Response:
    return await _process_remnawave_webhook(
        request=request,
        config=config,
        remna_webhook_service=remna_webhook_service,
        event_publisher=event_publisher,
    )
