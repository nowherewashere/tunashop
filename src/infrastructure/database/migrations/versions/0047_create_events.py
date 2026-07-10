"""Metrics & analytics layer (metrics spec §3, §4).

Adds the single append-only ``events`` table plus ``transactions.net_amount`` (the
PSP-settled, after-fee amount the payment metric needs — spec §4).

Numbering note: this branches off ``0045``. A parallel Telegram-Stars workstream
holds ``0046``; the two are independent heads off ``0045`` and get reconciled at
integration (``alembic merge`` / renumber) — see the metrics runbook.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- events: one flat, append-only analytics store keyed by remnawave_uuid ---
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("UTC", sa.func.now()),
            nullable=False,
        ),
        sa.Column("user_ref", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("ix_events_event_type_ts", "events", ["event_type", "ts"])
    op.create_index("ix_events_user_ref_ts", "events", ["user_ref", "ts"])
    op.create_index(
        "ix_events_properties_gin", "events", ["properties"], postgresql_using="gin"
    )

    # --- transactions.net_amount: settled-after-fee amount from the PSP webhook ---
    # Nullable: not every gateway exposes a fee in its webhook, and those payments
    # keep net = NULL (excluded from the real fee curve rather than guessed).
    op.add_column(
        "transactions",
        sa.Column("net_amount", sa.Numeric(precision=18, scale=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "net_amount")

    op.drop_index("ix_events_properties_gin", table_name="events")
    op.drop_index("ix_events_user_ref_ts", table_name="events")
    op.drop_index("ix_events_event_type_ts", table_name="events")
    op.drop_table("events")
