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
    reward_type: str
    reward_strategy: str
    accrual_strategy: str
    max_level: int
    reward_levels: list[ReferralRewardLevelResponse]
