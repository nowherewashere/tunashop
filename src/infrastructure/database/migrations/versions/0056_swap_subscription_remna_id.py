from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Second half of the UUID -> BigInt swap opened by 0055. Run this only after
    # `deploy/backfill_remna_ids.py` has resolved every row against the panel,
    # otherwise the guard below trips — which is the intended safety net, not a bug.
    connection = op.get_bind()
    unresolved = connection.execute(
        sa.text("SELECT count(*) FROM subscriptions WHERE user_remna_id_bigint IS NULL")
    ).scalar_one()
    if unresolved:
        raise RuntimeError(
            f"{unresolved} subscription(s) still have no panel id. "
            "Run `python deploy/backfill_remna_ids.py` first (before the panel "
            "upgrade); rows that stay unresolved belong to users deleted in the "
            "panel and must be retired manually before this migration can proceed."
        )

    op.drop_index("ix_subscriptions_user_remna_id", table_name="subscriptions")
    op.drop_column("subscriptions", "user_remna_id")

    op.alter_column(
        "subscriptions",
        "user_remna_id_bigint",
        new_column_name="user_remna_id",
        nullable=False,
    )
    op.drop_index("ix_subscriptions_user_remna_id_bigint", table_name="subscriptions")
    op.create_index("ix_subscriptions_user_remna_id", "subscriptions", ["user_remna_id"])


def downgrade() -> None:
    # The original UUIDs are gone for good once 0055's source column is dropped, so
    # this only restores the shape — the values cannot come back.
    op.drop_index("ix_subscriptions_user_remna_id", table_name="subscriptions")
    op.alter_column(
        "subscriptions",
        "user_remna_id",
        new_column_name="user_remna_id_bigint",
        nullable=True,
    )
    op.create_index(
        "ix_subscriptions_user_remna_id_bigint",
        "subscriptions",
        ["user_remna_id_bigint"],
    )
    op.add_column(
        "subscriptions",
        sa.Column("user_remna_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_subscriptions_user_remna_id", "subscriptions", ["user_remna_id"])
