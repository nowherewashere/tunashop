from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import Float, cast, func, select

from src.application.common.dao import EventsDao
from src.application.dto.metrics import PaymentFeeRow
from src.core.metrics import MetricEvent
from src.infrastructure.database.models.event import Event

from .base import BaseDaoImpl


class EventsDaoImpl(BaseDaoImpl, EventsDao):
    # --- write side ---
    async def append(
        self,
        *,
        event_type: str,
        source: str,
        user_ref: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        self.session.add(
            Event(
                user_ref=user_ref,
                source=source,
                event_type=event_type,
                properties=properties or {},
            )
        )
        await self.session.flush()

    # --- read side (offline jobs, spec §8) ---
    async def has_event(self, *, user_ref: str, event_type: str) -> bool:
        result = await self.session.execute(
            select(Event.id)
            .where(Event.user_ref == user_ref, Event.event_type == event_type)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def count(
        self,
        *,
        event_type: str,
        since: datetime,
        until: datetime,
        source: Optional[str] = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Event)
            .where(
                Event.event_type == event_type,
                Event.ts >= since,
                Event.ts < until,
            )
        )
        if source is not None:
            stmt = stmt.where(Event.source == source)
        return int(await self.session.scalar(stmt) or 0)

    async def group_by_property(
        self,
        *,
        event_type: str,
        prop_key: str,
        since: datetime,
        until: datetime,
        source: Optional[str] = None,
    ) -> dict[str, int]:
        key = Event.properties[prop_key].astext
        stmt = (
            select(key, func.count())
            .where(
                Event.event_type == event_type,
                Event.ts >= since,
                Event.ts < until,
                key.is_not(None),
            )
            .group_by(key)
        )
        if source is not None:
            stmt = stmt.where(Event.source == source)
        result = await self.session.execute(stmt)
        return {str(value): int(total) for value, total in result.all()}

    async def payment_fee_rows(
        self, *, since: datetime, until: datetime
    ) -> list[PaymentFeeRow]:
        stmt = select(
            Event.properties["gross"].astext,
            Event.properties["net"].astext,
            Event.properties["currency"].astext,
            Event.properties["plan"].astext,
        ).where(
            Event.event_type == MetricEvent.PAYMENT,
            Event.ts >= since,
            Event.ts < until,
        )
        result = await self.session.execute(stmt)
        rows: list[PaymentFeeRow] = []
        for gross_raw, net_raw, currency, plan in result.all():
            gross = self._to_decimal(gross_raw)
            if gross is None:
                continue
            rows.append(
                PaymentFeeRow(
                    gross=gross,
                    net=self._to_decimal(net_raw),
                    currency=currency or "",
                    plan=plan,
                )
            )
        return rows

    async def lifetime_days(self, *, since: datetime, until: datetime) -> list[float]:
        # Earliest first_connect per user (= lifetime start, spec §4).
        first_connect = (
            select(
                Event.user_ref.label("user_ref"),
                func.min(Event.ts).label("first_ts"),
            )
            .where(
                Event.event_type == MetricEvent.FIRST_CONNECT,
                Event.user_ref.is_not(None),
            )
            .group_by(Event.user_ref)
            .subquery()
        )
        days = cast(
            func.extract("epoch", Event.ts - first_connect.c.first_ts) / 86400.0,
            Float,
        )
        stmt = (
            select(days)
            .select_from(Event)
            .join(first_connect, Event.user_ref == first_connect.c.user_ref)
            .where(
                Event.event_type == MetricEvent.CHURNED,
                Event.ts >= since,
                Event.ts < until,
                Event.ts >= first_connect.c.first_ts,
            )
        )
        result = await self.session.execute(stmt)
        return [float(value) for (value,) in result.all() if value is not None]

    @staticmethod
    def _to_decimal(raw: Optional[str]) -> Optional[Decimal]:
        if raw is None:
            return None
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            return None
