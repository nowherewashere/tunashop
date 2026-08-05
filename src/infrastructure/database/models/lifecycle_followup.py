from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.constants import FOLLOWUP_PENDING

from .base import BaseSql
from .timestamp import TimestampMixin

# The row-lifecycle statuses and the chain ids are plain strings (not a PG enum) to
# keep the feature a single additive table, mirroring `onboarding_nudges`. They live
# in `src.core.constants`, where the layers above this one can read them without
# importing infrastructure.


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
