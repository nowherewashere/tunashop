from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.core.enums import ReferralLevel, ReferralRewardType

from .base import BaseDto, TimestampMixin, TrackableMixin
from .user import UserDto


@dataclass(kw_only=True)
class ReferralDto(BaseDto, TrackableMixin, TimestampMixin):
    level: ReferralLevel

    referrer: "UserDto"
    referred: "UserDto"


@dataclass(kw_only=True)
class ReferralRewardDto(BaseDto, TrackableMixin, TimestampMixin):
    user_id: int

    type: ReferralRewardType
    amount: int
    is_issued: bool = False

    @property
    def rewarded_at(self) -> Optional[datetime]:
        return self.created_at
