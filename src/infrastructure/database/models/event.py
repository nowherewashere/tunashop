from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import NOW_FUNC


class Event(BaseSql):
    """The single append-only analytics store (metrics spec §3).

    One flat, additive table shared by bot + site + probes, keyed by
    ``remnawave_uuid`` (the spine that links bot↔site). No joins on write, flexible
    ``properties`` JSONB, near-zero write weight. Deliberately NOT a ``TimestampMixin``
    row: an event has exactly one time, ``ts`` — there is no "updated_at" for an
    immutable fact.
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=NOW_FUNC,
        nullable=False,
    )
    # remnawave_uuid; NULL for node-level / active-probe rows that aren't per-user.
    user_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # MetricSource
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)  # MetricEvent
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        # (type, ts): funnel/business rollups scan by event_type over a window.
        Index("ix_events_event_type_ts", "event_type", "ts"),
        # (user_ref, ts): per-user timelines (conversion, lifetime, "has X yet?").
        Index("ix_events_user_ref_ts", "user_ref", "ts"),
        # gin(properties): slice health by node/protocol/operator, plan mix, etc.
        Index("ix_events_properties_gin", "properties", postgresql_using="gin"),
    )
