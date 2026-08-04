from datetime import datetime
from typing import Final, Optional

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin

# Row lifecycle — plain strings (not a PG enum) to keep the feature a single
# additive table, mirroring `onboarding_nudges`.
FOLLOWUP_PENDING: Final[str] = "pending"
FOLLOWUP_SENT: Final[str] = "sent"
FOLLOWUP_CANCELLED: Final[str] = "cancelled"

# Followup chains (spec §6). The onboarding "A" chain lives in its own table; these
# are the post-connect / lifecycle chains driven by this unified dispatcher.
CHAIN_TRIAL_ENDING: Final[str] = "C"  # −3h before trial end — convert
CHAIN_WINBACK: Final[str] = "E"  # +3d / +2w after churn — win-back


class LifecycleFollowup(BaseSql, TimestampMixin):
    """One scheduled lifecycle followup (chains C/E, spec §6).

    Additive table modelled on ``onboarding_nudges``: armed by event listeners,
    swept by a cron task that re-validates live user state before sending, so no
    per-chain cancel events are required.
    """

    __tablename__ = "lifecycle_followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chain: Mapped[str] = mapped_column(String(8), index=True)
    step: Mapped[str] = mapped_column(String(32))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default=FOLLOWUP_PENDING, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
