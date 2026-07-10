from typing import Optional

from pydantic import BaseModel


class ReferralRewardLevelResponse(BaseModel):
    level: int
    value: int


class ReferralProgramResponse(BaseModel):
    enabled: bool
    referral_code: str
    # Ready-to-use invite links (built from the bot username / REFERRAL_SITE_URL,
    # single source). `site_referral_url` is null when REFERRAL_SITE_URL is unset.
    bot_referral_url: str
    site_referral_url: Optional[str] = None
    invited_count: int
    invited_with_payment_count: int

    # --- money referral (spec §2): amounts in kopecks; ₽ formatting is view-side. ---
    balance_kop: int = 0
    withdrawn_kop: int = 0
    spent_kop: int = 0
    lifetime_kop: int = 0
    # Gates / payout context so the UI can enable/disable actions without extra calls.
    payout_min_kop: int = 100_000
    has_open_payout: bool = False
    crypto_asset: str = "USDT"
    crypto_network: str = "TRC20"
    last_wallet: Optional[str] = None  # masked, prefill for repeat payouts
    # Telegram Stars payout (spec §7.2). Gifting needs Telegram/MTProto, so the site
    # surfaces Stars as "получить в боте" — this flag/threshold only drive that hint.
    stars_payout_enabled: bool = False
    stars_min_kop: int = 10_000

    # Legacy reward config (vestigial — the active accrual is the money commission).
    reward_type: str
    reward_strategy: str
    accrual_strategy: str
    max_level: int
    reward_levels: list[ReferralRewardLevelResponse]


class CryptoPayoutRequest(BaseModel):
    wallet: str


class StarsPayoutRequest(BaseModel):
    # None → gift the whole balance (default). A specific amount is clamped to balance.
    amount_kop: Optional[int] = None


class PayoutResponse(BaseModel):
    id: int
    status: str
    amount_kop: int
    method: str
    crypto_asset: Optional[str] = None
    crypto_network: Optional[str] = None
    stars_amount: Optional[int] = None  # XTR gifted (stars payouts only)


class PayWithBalanceRequest(BaseModel):
    plan_id: int
    duration_days: int


class PayWithBalanceResponse(BaseModel):
    ok: bool
    amount_kop: int
    new_expire_at: str  # ISO 8601
    balance_kop: int
