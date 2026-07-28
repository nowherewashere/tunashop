from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import OAuthProvider

from .base import BaseSql
from .timestamp import TimestampMixin


class UserOAuthProvider(BaseSql, TimestampMixin):
    __tablename__ = "user_oauth_providers"

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_oauth_providers_user_provider"),
        UniqueConstraint("provider", "provider_id", name="uq_user_oauth_providers_provider_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[OAuthProvider] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(255))
    # Address the provider reported at link time. DISPLAY ONLY — never an input to an
    # authentication decision (see migration 0053); matching happens on provider_id,
    # or on users.email guarded by the provider's signed email_verified claim.
    provider_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
