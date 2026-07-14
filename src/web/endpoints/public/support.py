import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Optional

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
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
from src.infrastructure.redis import SupportPubSubRedis
from src.infrastructure.redis.key_builder import serialize_storage_key
from src.infrastructure.redis.keys import SupportStreamCountKey
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

# History-poll guard (GET /messages): generous, because this is the client's polling
# fallback when the SSE stream can't be established and may fire every few seconds. A
# legitimate cabinet never approaches it; it only sheds a scripted hammer.
_HISTORY_RATE_LIMIT = 120
_HISTORY_RATE_WINDOW_SECONDS = 60

# Stream-open guard: opening a stream is comparatively expensive (it holds a dedicated
# pub/sub connection for the connection's whole lifetime), so cap how fast one account
# may (re)open them. Reconnects on flaky networks are normal, hence not tiny.
_STREAM_OPEN_RATE_LIMIT = 30
_STREAM_OPEN_RATE_WINDOW_SECONDS = 60

# Per-user concurrent-stream cap: one account may hold at most this many streams open at
# once (a normal cabinet uses one; a few tabs is fine; thousands is the abuse we block).
_MAX_STREAMS_PER_USER = 5
# The per-user counter self-heals: a live stream refreshes this TTL on every heartbeat,
# so it only lapses once no stream has touched it for this long — reclaiming a slot that
# a hard process kill mid-stream left un-decremented, so a crash can't lock an account
# out forever. Comfortably exceeds the heartbeat cadence.
_STREAM_SLOT_TTL_SECONDS = 300

# Process-wide ceiling on concurrent streams (mirrors the webhook semaphore in
# web/endpoints/telegram.py): a flood spread across many accounts still cannot exhaust
# the process's sockets or the dedicated pub/sub pool. When full we reject fast (503) so
# the site falls back to polling, rather than queueing and pinning a request + socket
# per waiter. Kept below the pub/sub pool bound so a stream never blocks on a connection.
_MAX_CONCURRENT_STREAMS = 200
_stream_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_STREAMS)

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
    rate_limiter: FromDishka[RateLimiter],
    after: int = Query(0, ge=0),
) -> SupportHistoryResponse:
    """Conversation history (initial load) or new messages after a cursor (polling)."""
    if not config.support.is_active:
        return SupportHistoryResponse(enabled=False, status=None, messages=[])

    within_limit = await rate_limiter.hit(
        "support_history",
        str(user.id),
        limit=_HISTORY_RATE_LIMIT,
        window_seconds=_HISTORY_RATE_WINDOW_SECONDS,
    )
    if not within_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited"
        )

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


async def _reserve_stream_slot(
    user_id: int, *, redis: Redis, rate_limiter: RateLimiter
) -> str:
    """Enforce the three SSE abuse caps and reserve one stream's slot.

    Returns the Redis slot key (to DECR on release) or raises ``HTTPException`` (429/503)
    when a cap is hit. On success the caller MUST release exactly once — the process
    permit and the per-user counter — via ``_release_stream_slot`` in its ``finally``.
    """
    # 1) Rate-limit OPENS per account — cheap, and no resource is held yet.
    if not await rate_limiter.hit(
        "support_stream_open",
        str(user_id),
        limit=_STREAM_OPEN_RATE_LIMIT,
        window_seconds=_STREAM_OPEN_RATE_WINDOW_SECONDS,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited"
        )

    # 2) Process-wide ceiling. Reject fast when full instead of queueing (a queued SSE
    #    request would pin a socket for an unbounded wait). The `locked()` check and the
    #    acquire are not separated by an `await`, so on the single-threaded event loop no
    #    other coroutine can take the last permit in between — the acquire never blocks.
    if _stream_semaphore.locked():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="stream_capacity"
        )
    await _stream_semaphore.acquire()

    # 3) Per-user concurrent-stream cap, counted in Redis (INCR now, DECR on close). The
    #    TTL self-heals a slot that a hard crash left un-decremented (see the constant).
    #    On a Redis hiccup here, release the permit and 503 — the site then polls.
    slot_key = serialize_storage_key(SupportStreamCountKey(user_id=user_id))
    try:
        active_streams = int(await redis.incr(slot_key))
        await redis.expire(slot_key, _STREAM_SLOT_TTL_SECONDS)
    except Exception as error:
        _stream_semaphore.release()
        logger.warning(f"support stream open failed for user {user_id}: {error}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="stream_unavailable"
        ) from error
    if active_streams > _MAX_STREAMS_PER_USER:
        await redis.decr(slot_key)
        _stream_semaphore.release()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_streams"
        )
    return slot_key


async def _release_stream_slot(slot_key: str, *, redis: Redis, user_id: int) -> None:
    """Give back the process permit and (best-effort) DECR the per-user counter.

    Called from the stream generator's ``finally``, so it fires on client disconnect,
    support-close, or an error alike. A lost DECR is reclaimed by the counter's TTL.
    """
    _stream_semaphore.release()
    try:
        await redis.decr(slot_key)
    except Exception as error:
        logger.warning(f"support stream slot release failed for user {user_id}: {error}")


@router.get("/stream")
@inject
async def stream_support_messages(
    request: Request,
    user: CurrentUser,
    support: FromDishka[SupportService],
    session: FromDishka[AsyncSession],
    redis: FromDishka[Redis],
    pubsub_redis: FromDishka[SupportPubSubRedis],
    rate_limiter: FromDishka[RateLimiter],
    config: FromDishka[AppConfig],
    after: int = Query(0, ge=0),
) -> StreamingResponse:
    """Server-sent events for the caller's conversation — operator replies and status
    changes pushed in near-real-time, so the cabinet stops polling `GET /messages`.

    History is still loaded once via `GET /messages` (after=0); this only streams what
    happens next. A non-200 response (e.g. support disabled, or an abuse cap tripped)
    makes the browser's EventSource raise an error, and the site falls back to polling.

    Every open stream holds a dedicated pub/sub connection for its whole lifetime, so
    three layered caps keep one account (or a flood across accounts) from exhausting the
    pub/sub pool / process sockets: an open-rate limit, a per-user concurrent cap, and a
    process-wide semaphore. The pub/sub connection also comes from a pool separate from
    the shared one, so even a breach can't starve the rate limiter or operator fan-out.
    """
    if not config.support.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="support_unavailable"
        )

    # Enforce the abuse caps and reserve a slot BEFORE committing to a 200 stream, so a
    # tripped cap surfaces as a real 429/503 the SPA can fall back on. Released in the
    # generator's `finally` below.
    slot_key = await _reserve_stream_slot(user.id, redis=redis, rate_limiter=rate_limiter)

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
        try:
            # The subscription uses the DEDICATED pub/sub pool; the counter/guard ops
            # above use the shared pool, so a stream flood never borrows a shared
            # connection out from under the rate limiter or the operator fan-out.
            async with pubsub_redis.pubsub() as pubsub:
                # Subscribe BEFORE the catch-up read: a reply stored during catch-up is
                # then buffered on the subscription and still delivered (deduped by id).
                await pubsub.subscribe(channel)

                conversation, missed = await support.list_messages(user, after_id=resume_from)
                # From here the stream only reads Redis — release the pooled DB
                # connection so a long-lived SSE never pins a session for its lifetime.
                await session.close()

                # 1) Replay anything stored past the cursor (initial / reconnect gap),
                #    then the current status so a reconnect refreshes the open/closed banner.
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
                #    On client disconnect Starlette cancels this generator; the `finally`
                #    below frees the slot and the `async with` returns the connection.
                while True:
                    pub = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=_HEARTBEAT_SECONDS
                    )
                    # Keep the per-user slot alive for as long as the stream really is
                    # (best-effort — a failed refresh must not kill a healthy stream).
                    try:
                        await redis.expire(slot_key, _STREAM_SLOT_TTL_SECONDS)
                    except Exception:
                        pass
                    if pub is None:
                        yield ": keep-alive\n\n"
                        continue
                    payload = pub["data"]
                    if isinstance(payload, bytes):  # defensive: if the pool isn't decoding
                        payload = payload.decode()
                    yield _sse_frame(payload, event_id=_message_event_id(payload))
        finally:
            await _release_stream_slot(slot_key, redis=redis, user_id=user.id)

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
