from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class UserConnectionState(BaseSql, TimestampMixin):
    """Local, additive per-user connection milestones.

    Kept as a standalone table (never a column on the shared ``User`` model) so the
    feature stays a clean fork addition with zero upstream-merge surface — the same
    approach used for ``onboarding_nudges``. Populated by the first-connection event
    listener; drives the hub's "connected once" button switch and the on-connect
    trial-timer restart.
    """

    __tablename__ = "user_connection_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    connected_once: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set once, when the trial clock is (re)started at first connection — the guard
    # that makes the restart idempotent.
    trial_restarted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
