from typing import Optional

from pydantic import BaseModel


class PublicConfigResponse(BaseModel):
    # Public Cloudflare Turnstile site key; null when the captcha is disabled.
    turnstile_site_key: Optional[str] = None
    # Trial length (days) referred friends get — the active INVITED trial plan's
    # duration, or null if no invited-only trial exists (no referral bonus). Drives the
    # "N дней бесплатно" pill dynamically instead of a hardcoded "72 часа".
    referred_trial_days: Optional[int] = None
