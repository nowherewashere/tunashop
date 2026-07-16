"""Metrics & analytics vocabulary (metrics spec §3–§6).

Central, dependency-free catalog for the append-only ``events`` table: the event
types, the ``source`` discriminator and the onboarding funnel steps. Kept in
``core`` (no application imports) so models, DAOs, the event
listener, the web endpoint and the offline jobs all speak the same strings —
single source of truth, exactly like ``core.enums`` is for the domain.

The values are plain lowercase strings on purpose: they land verbatim in the
``events.event_type`` / ``events.source`` / ``properties`` columns and in the
site's JSON payloads, so they must stay stable and human-readable.
"""

from enum import StrEnum
from typing import Final


class MetricSource(StrEnum):
    """``events.source`` — where the row was written from (spec §3)."""

    BOT = "bot"
    SITE = "site"
    PSP = "psp"


class MetricEvent(StrEnum):
    """``events.event_type`` — the closed catalog (spec §4–§6)."""

    # Business events (spec §4) — rare, light, one economic hypothesis each.
    TRIAL_STARTED = "trial_started"
    FIRST_CONNECT = "first_connect"
    TRIAL_CONVERTED = "trial_converted"
    PAYMENT = "payment"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    CHURNED = "churned"
    REFERRAL_ATTRIBUTED = "referral_attributed"

    # Funnel steps (spec §5) — same name on bot and site for comparability.
    FUNNEL_STEP = "funnel_step"

    # Health / viability (spec §6) — node status from Remnawave node webhooks.
    NODE_STATUS = "node_status"


class FunnelStep(StrEnum):
    """Onboarding funnel vocabulary (spec §5).

    ``start → device_selected → app_install_shown → config_issued`` are the UI
    transitions emitted by the bot/site as ``funnel_step`` rows. ``first_connect``
    and ``trial_converted`` complete the funnel but are recorded as their own
    business events (spec §4) — the offline job stitches the two together, so the
    client never emits them and we never double-count.
    """

    START = "start"
    DEVICE_SELECTED = "device_selected"
    APP_INSTALL_SHOWN = "app_install_shown"
    CONFIG_ISSUED = "config_issued"
    FIRST_CONNECT = "first_connect"
    TRIAL_CONVERTED = "trial_converted"


# The subset the bot/site actually emit as ``funnel_step`` rows (the tail two are
# business events). Used to validate the public site endpoint's input.
FUNNEL_UI_STEPS: Final[frozenset[str]] = frozenset(
    {
        FunnelStep.START,
        FunnelStep.DEVICE_SELECTED,
        FunnelStep.APP_INSTALL_SHOWN,
        FunnelStep.CONFIG_ISSUED,
    }
)


class ConnectOutcome(StrEnum):
    """``properties.outcome`` for connect / node events (spec §6.1)."""

    SUCCESS = "success"
    FAIL = "fail"


class NodeStatus(StrEnum):
    """``properties.status`` for ``node_status`` events (spec §6.1)."""

    UP = "up"
    DOWN = "down"


# `properties.method` marker for a balance-funded renewal (spec §3.4). The referral
# balance is already-earned commission, so such a renewal writes a `subscription_renewed`
# row tagged with this method and NO cash `payment` row — keeping revenue / the fee curve
# honest while still exposing referral cannibalization.
REFERRAL_BALANCE_METHOD: Final[str] = "referral_balance"

# Offline business rollup lookback (daily job, spec §8).
BUSINESS_ROLLUP_WINDOW_DAYS: Final[int] = 1

# Fee-curve buckets (₽) for the real net/gross curve (spec §8/§9): small, mid, large.
FEE_CURVE_BUCKETS_RUB: Final[tuple[int, ...]] = (300, 700, 1500)
