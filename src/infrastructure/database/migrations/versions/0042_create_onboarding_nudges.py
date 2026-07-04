from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "onboarding_nudges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_onboarding_nudges_telegram_id", "onboarding_nudges", ["telegram_id"]
    )
    op.create_index("ix_onboarding_nudges_fire_at", "onboarding_nudges", ["fire_at"])
    op.create_index("ix_onboarding_nudges_status", "onboarding_nudges", ["status"])


def downgrade() -> None:
    op.drop_index("ix_onboarding_nudges_status", table_name="onboarding_nudges")
    op.drop_index("ix_onboarding_nudges_fire_at", table_name="onboarding_nudges")
    op.drop_index("ix_onboarding_nudges_telegram_id", table_name="onboarding_nudges")
    op.drop_table("onboarding_nudges")
