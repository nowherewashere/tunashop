"""Fire-and-forget metrics-signal events (metrics spec §5, §4 referral).

These carry no user-facing message; they exist only so the in-process event bus
can fan them out to :class:`MetricsEventListener`, which turns them into rows in
the append-only ``events`` table.

**Why they subclass ``BaseEvent`` directly** (not ``SystemEvent`` / ``UserEvent``):
``NotificationService`` broadly subscribes to ``@on_event(SystemEvent)`` and
``@on_event(UserEvent)`` and would route any subclass to the admin/system chat.
A metrics signal must never notify anyone, so it sits one level below that fan-out
— the only listener that ever sees it is the metrics one. This mirrors the spec's
"logging must be invisible to the user" rule (§2, §7).
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from src.core.enums import SystemNotificationType
from src.core.metrics import FunnelStep, MetricSource
from src.core.types import NotificationType

from .base import BaseEvent


@dataclass(frozen=True, kw_only=True)
class MetricSignalEvent(BaseEvent):
    """Base for pure metrics signals — consumed only by ``MetricsEventListener``.

    ``notification_type`` is defaulted purely to satisfy ``BaseEvent``; nothing ever
    reads it for these events because no notification listener subscribes to
    ``BaseEvent`` (only to ``SystemEvent`` / ``UserEvent``).
    """

    notification_type: NotificationType = field(
        default=SystemNotificationType.SYSTEM,
        init=False,
    )


@dataclass(frozen=True, kw_only=True)
class FunnelStepEvent(MetricSignalEvent):
    """A single onboarding funnel transition (spec §5).

    Emitted from BOTH the bot (published on the bus) and the site (via the public
    ``/events/funnel`` endpoint, which re-publishes it) so the funnel is comparable
    across surfaces. ``user_ref`` (remnawave_uuid) is resolved by the listener from
    ``telegram_id`` when the caller doesn't already know it (e.g. the bot mid-funnel).
    """

    step: FunnelStep
    source: MetricSource
    platform: Optional[str] = None
    telegram_id: Optional[int] = None
    user_ref: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class ReferralCommissionRecordedEvent(MetricSignalEvent):
    """A money commission was just booked on a referred user's real payment.

    This is the spec's ``referral_attributed`` moment (§4): "referred user pays",
    carrying ``referrer_ref`` + ``payout_rub``. Published from ``RecordReferralCommission``
    the instant the ledger row is inserted (idempotent), so the metric mirrors the
    ledger exactly — no double count on retried webhooks.
    """

    referrer_id: int
    referred_id: int
    payment_id: str
    payment_kop: int
    commission_kop: int
    referred_telegram_id: Optional[int] = None
    referrer_remna_uuid: Optional[UUID] = None
