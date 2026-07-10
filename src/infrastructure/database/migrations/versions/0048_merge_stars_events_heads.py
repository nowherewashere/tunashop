"""Merge the two migration heads that branched off 0045.

Two independent workstreams each added a migration on top of ``0045``:
``0046`` (Telegram Stars payout — ``payouts`` columns) and ``0047`` (metrics
events table + ``transactions.net_amount``). They touch disjoint tables, so this
is a no-op merge that reunites the history into a single head — ``alembic upgrade
head`` then applies both branches in either order.
"""

from typing import Sequence, Union

revision: str = "0048"
down_revision: Union[str, Sequence[str], None] = ("0046", "0047")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
