from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # --- referral_events: money commission ledger (EARNED = Σ commission_kop) ---
    op.create_table(
        "referral_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "referrer_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "referred_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payment_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("payment_kop", sa.Integer(), nullable=False),
        sa.Column("commission_kop", sa.Integer(), nullable=False),
        sa.Column("rate_bp", sa.Integer(), nullable=False, server_default="5000"),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="commission"),
        *_timestamps(),
    )
    op.create_index("ix_referral_events_referrer_id", "referral_events", ["referrer_id"])
    op.create_index("ix_referral_events_referred_id", "referral_events", ["referred_id"])

    # --- payouts: withdrawal requests (WITHDRAWN = Σ amount_kop where status=paid) ---
    op.create_table(
        "payouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(length=16), nullable=False, server_default="crypto"),
        sa.Column("amount_kop", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="requested"),
        sa.Column("crypto_wallet", sa.String(length=128), nullable=True),
        sa.Column("crypto_asset", sa.String(length=16), nullable=True),
        sa.Column("crypto_network", sa.String(length=16), nullable=True),
        sa.Column("crypto_amount", sa.String(length=64), nullable=True),
        sa.Column("fx_rate", sa.String(length=64), nullable=True),
        sa.Column("tx_hash", sa.String(length=128), nullable=True),
        sa.Column("batch_id", sa.String(length=32), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_payouts_user_id", "payouts", ["user_id"])
    op.create_index("ix_payouts_status", "payouts", ["status"])
    op.create_index("ix_payouts_batch_id", "payouts", ["batch_id"])

    # --- balance_spends: VPN paid from balance (SPENT = Σ amount_kop) ---
    op.create_table(
        "balance_spends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_kop", sa.Integer(), nullable=False),
        sa.Column("applied_term", sa.Integer(), nullable=False),
        sa.Column("remnawave_ref", sa.String(length=64), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_balance_spends_user_id", "balance_spends", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_balance_spends_user_id", table_name="balance_spends")
    op.drop_table("balance_spends")

    op.drop_index("ix_payouts_batch_id", table_name="payouts")
    op.drop_index("ix_payouts_status", table_name="payouts")
    op.drop_index("ix_payouts_user_id", table_name="payouts")
    op.drop_table("payouts")

    op.drop_index("ix_referral_events_referred_id", table_name="referral_events")
    op.drop_index("ix_referral_events_referrer_id", table_name="referral_events")
    op.drop_table("referral_events")
