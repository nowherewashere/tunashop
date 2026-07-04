from typing import Sequence, Union

from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE settings
        SET extra = extra || '{"onboarding_enabled": false}'::jsonb
        WHERE NOT (extra ? 'onboarding_enabled')
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE settings
        SET extra = extra - 'onboarding_enabled'
    """)
