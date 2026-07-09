from datetime import datetime
from typing import Final, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin

# ---------------------------------------------------------------------------
# Money referral ledger (referral spec §2/§4).
#
# This is an *additive* money layer that runs alongside the reward-based
# `referrals` / `referral_rewards` tables (which stay untouched). All amounts are
# stored in kopecks (integer); rubles exist only at the view layer. Statuses /
# kinds are plain strings (not PG enums) to keep the whole feature a set of
# additive tables with no changes to the shared enum registry — mirroring
# `lifecycle_followups` / `onboarding_nudges`.
# ---------------------------------------------------------------------------

# referral_events.kind
EVENT_KIND_COMMISSION: Final[str] = "commission"
EVENT_KIND_ADJUSTMENT: Final[str] = "adjustment"  # chargeback reversal (external workstream)

# payouts.method (Telegram Stars is a later iteration)
PAYOUT_METHOD_CRYPTO: Final[str] = "crypto"

# payouts.status
PAYOUT_REQUESTED: Final[str] = "requested"
PAYOUT_PROCESSING: Final[str] = "processing"
PAYOUT_PAID: Final[str] = "paid"
PAYOUT_REJECTED: Final[str] = "rejected"

# A payout is "open" (locks further payouts + pay-with-balance) while in either
# of these states.
PAYOUT_OPEN_STATUSES: Final[tuple[str, ...]] = (PAYOUT_REQUESTED, PAYOUT_PROCESSING)


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
    """A withdrawal request (crypto in this iteration).

    ``WITHDRAWN = Σ amount_kop where status = paid``. Only one open payout
    (``requested``/``processing``) per user is allowed (enforced upstream). Crypto
    settlement runs in the weekly Monday batch; the operator marks the row
    ``paid`` (with ``tx_hash``) or ``rejected`` (with ``reject_reason``).
    """

    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(16), default=PAYOUT_METHOD_CRYPTO)
    amount_kop: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), default=PAYOUT_REQUESTED, index=True)

    # crypto settlement
    crypto_wallet: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    crypto_asset: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    crypto_network: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    crypto_amount: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # frozen@batch
    fx_rate: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # RUB->asset, frozen
    tx_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)

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
