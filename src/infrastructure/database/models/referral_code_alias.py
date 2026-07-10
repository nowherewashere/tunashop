from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class ReferralCodeAlias(BaseSql, TimestampMixin):
    """A referral code that outlived the account that owned it.

    An account merge deletes the absorbed row, taking its ``users.referral_code``
    with it. Every link already shared with that code would then stop attributing,
    and — because codes are only 6 characters — the freed code could later be
    re-issued to an unrelated new user, who would silently inherit those links.

    Tombstoning the code here, pointed at the survivor, fixes both: it is the
    single place that answers "who owns this code", live or historical.
    ``UserDao.get_by_referral_code`` falls back to this table, which makes inbound
    clicks credit the survivor *and* makes ``generate_unique_code`` treat the code
    as taken forever (it probes through the same lookup).

    The FK cascades like every other child table, so a survivor that is itself
    later absorbed must have its aliases repointed — see ``AccountMergeDao``.
    """

    __tablename__ = "referral_code_aliases"

    # The code itself is the identity: at most one owner, live or historical.
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
