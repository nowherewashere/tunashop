from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SendSupportMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class SupportMessageResponse(BaseModel):
    id: int
    # Maps the internal sender to the three roles the widget renders.
    author: Literal["user", "operator", "system"]
    text: str
    created_at: str  # ISO 8601


class SupportHistoryResponse(BaseModel):
    # False when SUPPORT_ENABLED is off — the widget shows the Telegram fallback link.
    enabled: bool
    status: Optional[str] = None  # open / closed
    messages: List[SupportMessageResponse]
