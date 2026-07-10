from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Referral codes of accounts absorbed by a merge. Keeps already-shared links
    # attributing to the survivor, and stops the 6-char code from being re-issued.
    op.create_table(
        "referral_code_aliases",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
    op.create_index("ix_referral_code_aliases_user_id", "referral_code_aliases", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_referral_code_aliases_user_id", table_name="referral_code_aliases")
    op.drop_table("referral_code_aliases")
