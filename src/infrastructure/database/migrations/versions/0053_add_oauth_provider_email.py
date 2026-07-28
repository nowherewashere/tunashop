from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The address the provider reported at link time, kept so the cabinet can say
    # WHICH Google account is attached ("Google · a***@gmail.com") instead of a bare
    # "connected" — which is useless to anyone holding more than one Google account.
    #
    # DISPLAY ONLY. This column is never an input to any authentication decision:
    # account matching runs on (provider, provider_id) and, for the auto-link case, on
    # users.email guarded by the provider's signed email_verified claim. Matching on a
    # remembered, possibly-unverified address here would be an account-takeover path.
    # Nullable: rows created before this migration have no recorded address.
    op.add_column(
        "user_oauth_providers",
        sa.Column("provider_email", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_oauth_providers", "provider_email")
