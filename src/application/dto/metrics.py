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
