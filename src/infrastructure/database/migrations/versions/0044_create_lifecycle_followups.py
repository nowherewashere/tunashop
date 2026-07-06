from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_followups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("chain", sa.String(length=8), nullable=False),
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
        "ix_lifecycle_followups_telegram_id", "lifecycle_followups", ["telegram_id"]
    )
    op.create_index("ix_lifecycle_followups_chain", "lifecycle_followups", ["chain"])
    op.create_index("ix_lifecycle_followups_fire_at", "lifecycle_followups", ["fire_at"])
    op.create_index("ix_lifecycle_followups_status", "lifecycle_followups", ["status"])


def downgrade() -> None:
    op.drop_index("ix_lifecycle_followups_status", table_name="lifecycle_followups")
    op.drop_index("ix_lifecycle_followups_fire_at", table_name="lifecycle_followups")
    op.drop_index("ix_lifecycle_followups_chain", table_name="lifecycle_followups")
    op.drop_index("ix_lifecycle_followups_telegram_id", table_name="lifecycle_followups")
    op.drop_table("lifecycle_followups")
