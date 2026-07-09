from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.infrastructure.database.models.referral_ledger import (
    EVENT_KIND_COMMISSION,
    PAYOUT_METHOD_CRYPTO,
    PAYOUT_REQUESTED,
)

from .base import BaseDto, TimestampMixin


@dataclass(kw_only=True)
class ReferralEventDto(BaseDto, TimestampMixin):
    referrer_id: int
    referred_id: int
    payment_id: str
    payment_kop: int
    commission_kop: int
    rate_bp: int = 5000
    kind: str = EVENT_KIND_COMMISSION


@dataclass(kw_only=True)
class PayoutDto(BaseDto, TimestampMixin):
    user_id: int
    amount_kop: int
    method: str = PAYOUT_METHOD_CRYPTO
    status: str = PAYOUT_REQUESTED
    #
    crypto_wallet: Optional[str] = None
    crypto_asset: Optional[str] = None
    crypto_network: Optional[str] = None
    crypto_amount: Optional[str] = None
    fx_rate: Optional[str] = None
    tx_hash: Optional[str] = None
    batch_id: Optional[str] = None
    #
    reject_reason: Optional[str] = None
    processed_at: Optional[datetime] = None
    operator_id: Optional[int] = None
    note: Optional[str] = None


@dataclass(kw_only=True)
class BalanceSpendDto(BaseDto, TimestampMixin):
    user_id: int
    amount_kop: int
    applied_term: int
    remnawave_ref: Optional[str] = None


@dataclass(frozen=True)
class ReferralSummaryDto:
    """The six derived quantities the bot and site both render (referral spec §2).

    Identity kept on both surfaces:
        lifetime_kop (EARNED) = balance_kop + withdrawn_kop + spent_kop
    """

    invited: int
    paying: int
    earned_kop: int
    spent_kop: int
    withdrawn_kop: int
    has_open_payout: bool

    @property
    def balance_kop(self) -> int:
        return self.earned_kop - self.spent_kop - self.withdrawn_kop

    @property
    def lifetime_kop(self) -> int:
        return self.earned_kop
