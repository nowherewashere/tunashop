from typing import Optional

from pydantic import BaseModel


class PublicPlanPoolResponse(BaseModel):
    """A metered premium-location pool advertised on a public plan card."""

    pool_id: int
    name: str
    quota_bytes: int
    # Panel vocabulary (DAY / WEEK / MONTH / MONTH_ROLLING / NO_RESET); the site words
    # the period itself rather than rendering a phrase chosen server-side.
    reset_strategy: str


class PublicPlanLandingResponse(BaseModel):
    public_code: str
    name: str
    description: Optional[str] = None
    # Per-plan flag/location string (opaque emoji text), e.g. "🇩🇪 | 🇯🇵 | 🇷🇺".
    locations: Optional[str] = None
    traffic_limit: int
    device_limit: int
    monthly_from_rub: str
    max_duration_days: int
    max_duration_price_rub: str
    # Optional with a None default, like `locations`: the landing response is cached in
    # Redis, and a payload written before this field existed must still validate.
    pools: Optional[list[PublicPlanPoolResponse]] = None


class PublicPlanLandingListResponse(BaseModel):
    plans: list[PublicPlanLandingResponse]
