from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# NOTE: a parallel metrics task branched 0047 off the same 0045 parent (disjoint
# tables — payouts columns here, a new events table there), so this and 0047 are
# two heads off 0045. They are reunited by the no-op merge migration 0048, which
# restores a single head for `alembic upgrade head`.
revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Telegram Stars payout (spec §7.2). Additive nullable columns on `payouts`;
    # crypto payouts leave them NULL. `recipient_tg` snapshots the gift target;
    # `stars_amount`/`stars_rate` freeze the RUB→⭐ conversion at request time;
    # `gift_ref`/`treasury_account` record settlement (the Stars analogue of tx_hash).
    op.add_column("payouts", sa.Column("recipient_tg", sa.String(length=64), nullable=True))
    op.add_column("payouts", sa.Column("stars_amount", sa.Integer(), nullable=True))
    op.add_column("payouts", sa.Column("stars_rate", sa.Integer(), nullable=True))
    op.add_column("payouts", sa.Column("gift_ref", sa.String(length=128), nullable=True))
    op.add_column("payouts", sa.Column("treasury_account", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("payouts", "treasury_account")
    op.drop_column("payouts", "gift_ref")
    op.drop_column("payouts", "stars_rate")
    op.drop_column("payouts", "stars_amount")
    op.drop_column("payouts", "recipient_tg")
