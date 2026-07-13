from typing import Optional

from pydantic import BaseModel, Field


class SupportConfigResponse(BaseModel):
    # True when the live in-cabinet support chat is on (SUPPORT_ENABLED). When false,
    # the widget falls back to the Telegram contact link below.
    enabled: bool = False
    # Telegram contact used as the fallback (and "open in Telegram" alternative).
    telegram_url: Optional[str] = None


class PublicConfigResponse(BaseModel):
    # Public Cloudflare Turnstile site key; null when the captcha is disabled.
    turnstile_site_key: Optional[str] = None
    # Trial length (days) referred friends get — the active INVITED trial plan's
    # duration, or null if no invited-only trial exists (no referral bonus). Drives the
    # "N дней бесплатно" pill dynamically instead of a hardcoded "72 часа".
    referred_trial_days: Optional[int] = None
    # Support-chat availability + fallback contact for the cabinet widget.
    support: SupportConfigResponse = Field(default_factory=SupportConfigResponse)
