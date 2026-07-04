from datetime import datetime
from typing import Final, Optional

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin

# Nudge row lifecycle. Kept as plain strings (not a PG enum) so the feature stays a
# single additive table with no changes to the shared enum registry.
NUDGE_PENDING: Final[str] = "pending"
NUDGE_SENT: Final[str] = "sent"
NUDGE_CANCELLED: Final[str] = "cancelled"


class OnboardingNudge(BaseSql, TimestampMixin):
    __tablename__ = "onboarding_nudges"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    step: Mapped[str] = mapped_column(String(32))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default=NUDGE_PENDING, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
