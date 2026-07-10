from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True, kw_only=True)
class PaymentFeeRow:
    """One ``payment`` row's gross/net pair (metrics spec §8 fee curve).

    ``net`` is None when the PSP webhook didn't expose a settled-after-fee amount
    for that gateway — those rows are excluded from the real fee curve rather than
    guessed at.
    """

    gross: Decimal
    net: Optional[Decimal]
    currency: str
    plan: Optional[str]


@dataclass(frozen=True, kw_only=True)
class NodeInfoDto:
    """Light node projection for active probes (metrics spec §6.2). Just enough to
    reach the node and label its probe row — not the full Remnawave node model."""

    uuid: str
    name: str
    address: str
    port: Optional[int]
    is_connected: bool
    is_disabled: bool
    country_code: Optional[str]


@dataclass(frozen=True, kw_only=True)
class HealthRow:
    """Success/total for one (node × protocol × operator) slice (spec §6.1, §8)."""

    node_id: str
    protocol: Optional[str]
    operator: Optional[str]
    success: int
    total: int

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total else 0.0
