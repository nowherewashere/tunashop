from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remnawave 3.0.0 dropped the user UUID: the panel's public identifier is now a
    # numeric BigInt id, so every UUID we stored is meaningless against a 3.x panel.
    #
    # The swap runs in two migrations with a backfill in between, because the values
    # cannot be derived locally. This migration only opens the new nullable column;
    # `deploy/backfill_remna_ids.py` fills it, and 0056 makes it the real one.
    #
    # Order on prod is fixed, and the backfill runs BEFORE the panel upgrade — on 2.8
    # a user still carries both `uuid` and the numeric `id` that 3.x keeps, which makes
    # the mapping exact instead of a username guess:
    #
    #   0055 -> backfill (panel still 2.8) -> upgrade panel + nodes -> 0056 -> bot
    op.add_column(
        "subscriptions",
        sa.Column("user_remna_id_bigint", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_subscriptions_user_remna_id_bigint",
        "subscriptions",
        ["user_remna_id_bigint"],
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_user_remna_id_bigint", table_name="subscriptions")
    op.drop_column("subscriptions", "user_remna_id_bigint")
