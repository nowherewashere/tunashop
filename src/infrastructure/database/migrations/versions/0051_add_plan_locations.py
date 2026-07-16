from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-plan flag/location string, replacing the former global PLAN_LOCATIONS env.
    # Nullable with no backfill: existing plans start empty and admins fill each in the
    # bot; the plan card omits the "Локации" line while the value is NULL.
    op.add_column("plans", sa.Column("locations", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "locations")
