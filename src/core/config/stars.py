from typing import Final

from .base import BaseConfig

# STARS_MODE values (spec §5.5/§10). Beta is operator-assisted; the automated
# self-bot gifter (mtproto_auto) is ToS-sensitive and gated behind the §12 D7 read.
STARS_MODE_OPERATOR: Final[str] = "operator"
STARS_MODE_MTPROTO_AUTO: Final[str] = "mtproto_auto"


class StarsConfig(BaseConfig, env_prefix="STARS_"):
    """Telegram Stars payout config (referral spec §7.2/§10).

    A Stars payout converts the referral balance to whole Stars and gifts them to
    the user's linked Telegram account. Stars are spendable **inside Telegram only**
    (not fiat), so this is an in-ecosystem reward, not a cash-out. Beta runs
    ``mode=operator``: the operator gifts from the Fragment-funded treasury account
    and marks the row paid with a ``gift_ref``.
    """

    # Master switch. Operator mode is ToS-safe; only ``mtproto_auto`` needs the D7 read.
    payout_enabled: bool = False
    # Kopecks per 1 Star, frozen on the row at request time. This is the retail
    # sourcing cost of a Star — set it to what a Star actually costs to buy/gift
    # (e.g. via Fragment) so a payout never gifts more value than the balance. A
    # value ≤ 0 disables Stars payouts (guards against a division by zero).
    rub_rate: int = 200
    # Small floor to request a Stars payout (kopecks): 10000 = 100 ₽. No 1000 ₽ gate.
    min_kop: int = 10_000
    # Fragment-funded account holding/gifting the Stars float (informational snapshot).
    treasury_account: str = ""
    # fragment (via crypto/TON) — preferred | appstore. Cost-accounting hint only.
    sourcing: str = "fragment"
    # operator (beta) | mtproto_auto (future, D7 sign-off).
    mode: str = STARS_MODE_OPERATOR
