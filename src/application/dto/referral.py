from dataclasses import dataclass
from typing import Optional

from src.core.enums import ReferralLevel

from .base import BaseDto, TimestampMixin, TrackableMixin
from .user import UserDto


@dataclass(kw_only=True)
class ReferralDto(BaseDto, TrackableMixin, TimestampMixin):
    level: ReferralLevel

    referrer: "UserDto"
    referred: "UserDto"


@dataclass(frozen=True)
class UserReferralStatsDto:
    """Who invited this user. Counts and money live in ``ReferralSummaryDto``."""

    referrer_telegram_id: Optional[int]
    referrer_email: Optional[str]
    referrer_username: Optional[str]
