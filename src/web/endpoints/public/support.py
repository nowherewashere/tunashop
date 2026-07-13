import json
from collections.abc import AsyncGenerator
from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common import SupportService
from src.application.common.dao import RateLimiter
from src.application.common.support import (
    build_message_event,
    build_status_event,
    support_events_channel,
)
from src.application.dto import SupportMessageDto
from src.core.config import AppConfig
from src.core.exceptions import SupportUnavailableError
from src.infrastructure.database.models.support import (
    CHANNEL_SITE,
    author_for_sender,
)
from src.web.schemas import (
    SendSupportMessageRequest,
    SupportHistoryResponse,
    SupportMessageResponse,
)

from ._common import CurrentUser

router = APIRouter(prefix="/support", tags=["Public - Support"])

# Per-user send guard: support is chatty but a page cannot flood the operator group.
_SEND_RATE_LIMIT = 20
_SEND_RATE_WINDOW_SECONDS = 60
_MAX_MESSAGE_LEN = 4000

# SSE heartbeat cadence: a comment frame every N seconds keeps the connection alive
# through browser/proxy idle timeouts when the conversation is quiet.
_HEARTBEAT_SECONDS = 20.0


def _to_response(message: SupportMessageDto) -> SupportMessageResponse:
    return SupportMessageResponse(
        id=message.id,
        author=author_for_sender(message.sender),
        text=message.text,
        created_at=message.created_at.isoformat() if message.created_at else "",
    )


@router.get("/messages", response_model=SupportHistoryResponse)
@inject
async def get_support_messages(
    user: CurrentUser,
    support: FromDishka[SupportService],
    config: FromDishka[AppConfig],
    after: int = Query(0, ge=0),
) -> SupportHistoryResponse:
    """Conversation history (initial load) or new messages after a cursor (polling)."""
    if not config.support.is_active:
        return SupportHistoryResponse(enabled=False, status=None, messages=[])

    conversation, messages = await support.list_messages(user, after_id=after)
    return SupportHistoryResponse(
        enabled=True,
        status=conversation.status if conversation else None,
        messages=[_to_response(message) for message in messages],
    )


def _sse_frame(payload: str, *, event_id: Optional[int] = None) -> str:
    """Format one SSE frame. `event_id` sets the `id:` line so the browser replays it
    as `Last-Event-ID` on reconnect (used to resume without gaps)."""
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {payload}\n\n"


def _message_event_id(payload: str) -> Optional[int]:
    """Message id inside a published `message` envelope, for the SSE `id:` cursor.
    Status envelopes carry no id (they must not move the resume cursor)."""
    try:
        event = json.loads(payload)
    except (TypeError, ValueError):
        return None
    message = event.get("message") if isinstance(event, dict) else None
    if isinstance(message, dict):
        message_id = message.get("id")
        if isinstance(message_id, int):
            return message_id
    return None


@router.get("/stream")
@inject
async def stream_support_messages(
    request: Request,
    user: CurrentUser,
    support: FromDishka[SupportService],
    session: FromDishka[AsyncSession],
    redis: FromDishka[Redis],
    config: FromDishka[AppConfig],
    after: int = Query(0, ge=0),
) -> StreamingResponse:
    """Server-sent events for the caller's conversation — operator replies and status
    changes pushed in near-real-time, so the cabinet stops polling `GET /messages`.

    History is still loaded once via `GET /messages` (after=0); this only streams what
    happens next. A non-200 response (e.g. support disabled) makes the browser's
    EventSource raise an error, and the site falls back to polling.
    """
    if not config.support.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="support_unavailable"
        )

    # Resume point: the browser replays its last delivered id as `Last-Event-ID` on a
    # reconnect; the first connection uses the `after` cursor from the history load.
    # Max of the two so neither the initial gap nor a reconnect gap drops a message
    # (any overlap is deduped client-side by id).
    resume_from = after
    last_event_id = request.headers.get("last-event-id")
    if last_event_id and last_event_id.isdigit():
        resume_from = max(resume_from, int(last_event_id))

    channel = support_events_channel(user.id)

    async def event_stream() -> AsyncGenerator[str, None]:
        async with redis.pubsub() as pubsub:
            # Subscribe BEFORE the catch-up read: a reply stored during catch-up is then
            # buffered on the subscription and still delivered (deduped by id) — no gap.
            await pubsub.subscribe(channel)

            conversation, missed = await support.list_messages(user, after_id=resume_from)
            # From here the stream only reads Redis — release the pooled DB connection so
            # a long-lived SSE never pins a session for its whole lifetime.
            await session.close()

            # 1) Replay anything stored past the cursor (initial / reconnect gap), then
            #    the current status so a reconnect refreshes the open/closed banner.
            for message in missed:
                event = build_message_event(
                    id=message.id,
                    author=author_for_sender(message.sender),
                    text=message.text,
                    created_at=message.created_at.isoformat() if message.created_at else "",
                )
                yield _sse_frame(json.dumps(event), event_id=message.id)
            if conversation is not None:
                yield _sse_frame(json.dumps(build_status_event(conversation.status)))

            # 2) Live: forward published events; emit a heartbeat on each idle timeout.
            #    On client disconnect Starlette cancels this generator; `async with`
            #    unsubscribes and returns the pub/sub connection to the pool.
            while True:
                pub = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_HEARTBEAT_SECONDS
                )
                if pub is None:
                    yield ": keep-alive\n\n"
                    continue
                payload = pub["data"]
                if isinstance(payload, bytes):  # defensive: if the pool isn't decoding
                    payload = payload.decode()
                yield _sse_frame(payload, event_id=_message_event_id(payload))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Belt-and-suspenders: also disable nginx buffering for THIS response even
            # if `proxy_buffering off` is missing on the edge (see deploy notes).
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/messages", response_model=SupportMessageResponse)
@inject
async def send_support_message(
    body: SendSupportMessageRequest,
    user: CurrentUser,
    support: FromDishka[SupportService],
    rate_limiter: FromDishka[RateLimiter],
) -> SupportMessageResponse:
    """Post a message from the cabinet; relays it into the user's operator topic."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty_message")
    text = text[:_MAX_MESSAGE_LEN]

    within_limit = await rate_limiter.hit(
        "support_send",
        str(user.id),
        limit=_SEND_RATE_LIMIT,
        window_seconds=_SEND_RATE_WINDOW_SECONDS,
    )
    if not within_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited"
        )

    try:
        message = await support.ingest_from_user(user, text, CHANNEL_SITE)
    except SupportUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="support_unavailable"
        ) from error

    return _to_response(message)
