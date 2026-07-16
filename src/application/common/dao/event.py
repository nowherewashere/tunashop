from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable

from src.application.dto.metrics import PaymentFeeRow


@runtime_checkable
class EventsDao(Protocol):
    """Read/write access to the append-only ``events`` table (metrics spec §3, §8).

    The write side (``append``) is best-effort and off the user's critical path;
    the read side backs the offline daily job. Everything is keyed on
    ``user_ref`` (remnawave_uuid) so bot + site data auto-consolidate.
    """

    # --- write side (fire-and-forget) ---
    async def append(
        self,
        *,
        event_type: str,
        source: str,
        user_ref: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        """Insert one event row. Never raises into the caller (best-effort)."""
        ...

    # --- read side (offline computation, spec §8) ---
    async def has_event(self, *, user_ref: str, event_type: str) -> bool:
        """True iff at least one such event already exists for this user_ref
        (used to detect first-payment → ``trial_converted`` without double count)."""
        ...

    async def count(
        self,
        *,
        event_type: str,
        since: datetime,
        until: datetime,
        source: Optional[str] = None,
    ) -> int: ...

    async def group_by_property(
        self,
        *,
        event_type: str,
        prop_key: str,
        since: datetime,
        until: datetime,
        source: Optional[str] = None,
    ) -> dict[str, int]:
        """Count rows grouped by a top-level ``properties`` key — plan mix,
        funnel step counts, payment method mix, etc."""
        ...

    async def payment_fee_rows(
        self, *, since: datetime, until: datetime
    ) -> list[PaymentFeeRow]:
        """All ``payment`` rows' gross/net pairs in the window (real fee curve)."""
        ...

    async def lifetime_days(self, *, since: datetime, until: datetime) -> list[float]:
        """Paying-lifetime samples: ``churned.ts − first_connect.ts`` in days, for
        users whose ``churned`` fell in the window (cohort lifetime, spec §8/§9)."""
        ...
