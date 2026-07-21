from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Optional influencer/owner of a promocode: on successful activation the redeeming user
    # is attached to this owner's referral so the influencer earns commission on the user's
    # future payments. Nullable — existing codes stay owner-less (plain promocodes).
    # ON DELETE SET NULL: deleting the owner must never delete the promocode. The account
    # merge DAO repoints this column so an absorbed influencer keeps their codes.
    op.add_column(
        "promocodes",
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_promocodes_owner_user_id"),
        "promocodes",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_promocodes_owner_user_id"), table_name="promocodes")
    op.drop_column("promocodes", "owner_user_id")
