from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enums import ReferralLevel

from .base import BaseSql
from .timestamp import TimestampMixin
from .user import User


class Referral(BaseSql, TimestampMixin):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    referred_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )

    level: Mapped[ReferralLevel]

    referrer: Mapped["User"] = relationship(
        lazy="selectin",
        foreign_keys=[referrer_id],
    )
    referred: Mapped["User"] = relationship(
        lazy="selectin",
        foreign_keys=[referred_id],
    )
