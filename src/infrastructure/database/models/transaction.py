from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.enums import Currency, PaymentGatewayType, PurchaseType, TransactionStatus

from .base import BaseSql
from .timestamp import TimestampMixin
from .user import User


class Transaction(BaseSql, TimestampMixin):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(index=True, unique=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    status: Mapped[TransactionStatus] = mapped_column(index=True)
    is_test: Mapped[bool]

    purchase_type: Mapped[PurchaseType]
    gateway_type: Mapped[PaymentGatewayType]
    gateway_display_name: Mapped[Optional[str]]
    payment_method: Mapped[Optional[str]]

    pricing: Mapped[dict[str, Any]]
    currency: Mapped[Currency]
    plan_snapshot: Mapped[dict[str, Any]]

    # Settled-after-fee amount from the PSP webhook (metrics spec §4). NULL when the
    # gateway's webhook doesn't expose a fee — kept out of the real fee curve then.
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
