from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Claim ledger for the "+1 trial day" broadcast button.

    Nullable and unindexed on purpose: the claim is always read through the existing
    (broadcast_id, user_id) pair, and the one-per-person guarantee comes from the
    atomic `UPDATE ... WHERE bonus_claimed_at IS NULL RETURNING id`, not from a
    constraint. Rows are removed with their broadcast by the 7-day cleanup task.
    """
    op.add_column(
        "broadcast_messages",
        sa.Column("bonus_claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("broadcast_messages", "bonus_claimed_at")
