from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_connection_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "connected_once", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("first_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_restarted_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_user_connection_states_telegram_id",
        "user_connection_states",
        ["telegram_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_connection_states_telegram_id", table_name="user_connection_states"
    )
    op.drop_table("user_connection_states")
