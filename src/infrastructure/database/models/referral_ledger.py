from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.constants import (
    EVENT_KIND_COMMISSION,
    PAYOUT_METHOD_CRYPTO,
    PAYOUT_REQUESTED,
)

from .base import BaseSql
from .timestamp import TimestampMixin

# ---------------------------------------------------------------------------
# Money referral ledger (referral spec §2/§4).
#
# This is an *additive* money layer that runs alongside the reward-based
# `referrals` / `referral_rewards` tables (which stay untouched). All amounts are
# stored in kopecks (integer); rubles exist only at the view layer. The kind /
# status / method strings these columns default to live in `src.core.constants`,
# where the layers above this one can read them without importing infrastructure.
# ---------------------------------------------------------------------------


class ReferralEvent(BaseSql, TimestampMixin):
    """One recorded commission on a referred user's real-money payment.

    ``EARNED = Σ commission_kop`` for a referrer. Counted the moment the row
    exists — no hold/pending state. Idempotent on ``payment_id``. A chargeback
    reversal (external workstream) appends a row with ``kind='adjustment'`` and a
    negative ``commission_kop`` so ``EARNED`` self-corrects.
    """

    __tablename__ = "referral_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    referred_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    payment_id: Mapped[str] = mapped_column(String(64), unique=True)  # idempotency key
    payment_kop: Mapped[int]
    commission_kop: Mapped[int]  # may be NEGATIVE for a chargeback adjustment
    rate_bp: Mapped[int] = mapped_column(default=5000)
    kind: Mapped[str] = mapped_column(String(16), default=EVENT_KIND_COMMISSION)


class Payout(BaseSql, TimestampMixin):
    """A withdrawal request (crypto or Telegram Stars).

    ``WITHDRAWN = Σ amount_kop where status = paid``. Only one open payout
    (``requested``/``processing``) per user is allowed (enforced upstream). Crypto
    settlement runs in the weekly Monday batch; Stars settle immediately (operator
    gifts from the treasury account). The operator marks the row ``paid`` — with a
    ``tx_hash`` (crypto) or ``gift_ref`` (stars) — or ``rejected`` (with a reason).
    """

    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(16), default=PAYOUT_METHOD_CRYPTO)
    amount_kop: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), default=PAYOUT_REQUESTED, index=True)
    # @username / tg id snapshot, captured at request time so a Stars gift can still
    # be delivered even if the user later unlinks Telegram.
    recipient_tg: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # crypto settlement
    crypto_wallet: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    crypto_asset: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    crypto_network: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    crypto_amount: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # frozen@batch
    fx_rate: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # RUB->asset, frozen
    tx_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)

    # stars settlement (buy-and-gift; spec §7.2)
    stars_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # XTR gifted
    stars_rate: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # kopecks per Star, frozen at request
    gift_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # MTProto gift ref
    treasury_account: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # operator bookkeeping
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # operator tg id
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class BalanceSpend(BaseSql, TimestampMixin):
    """VPN subscription paid from referral balance (``method = balance``).

    ``SPENT = Σ amount_kop``. Generates no commission to this user's referrer
    (anti-loop): pay-with-balance bypasses the PSP path entirely, so the payment
    commission seam never fires for it.
    """

    __tablename__ = "balance_spends"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    amount_kop: Mapped[int]
    applied_term: Mapped[int]  # days added to the subscription
    remnawave_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
