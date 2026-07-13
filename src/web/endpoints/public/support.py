from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, Query, status

from src.application.common import SupportService
from src.application.common.dao import RateLimiter
from src.application.dto import SupportMessageDto
from src.core.config import AppConfig
from src.core.exceptions import SupportUnavailableError
from src.infrastructure.database.models.support import (
    CHANNEL_SITE,
    SENDER_OPERATOR,
    SENDER_SYSTEM,
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


def _to_response(message: SupportMessageDto) -> SupportMessageResponse:
    if message.sender == SENDER_OPERATOR:
        author = "operator"
    elif message.sender == SENDER_SYSTEM:
        author = "system"
    else:
        author = "user"
    return SupportMessageResponse(
        id=message.id,
        author=author,
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
