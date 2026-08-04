from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reuse the PG enum the plans table already declares — the reset period of a pool
# quota is the same vocabulary as the panel's traffic-limit strategy. create_type=False
# stops Alembic from trying to CREATE TYPE a second time.
_STRATEGY = postgresql.ENUM(
    "NO_RESET",
    "DAY",
    "WEEK",
    "MONTH",
    "MONTH_ROLLING",
    name="plan_traffic_limit_strategy",
    create_type=False,
)


def upgrade() -> None:
    # A pool is one internal squad that contains the inbounds of premium nodes only.
    # Metering is per NODE (Xray has no per-user-per-inbound counter), which is why a
    # metered location must be its own node and a pool must be its own squad.
    op.create_table(
        "traffic_pools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        # The squad whose nodes are metered AND the squad withdrawn on exhaustion —
        # one and the same, so a pool can never meter one thing and cut another.
        sa.Column(
            "internal_squad_uuid",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
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

    # Per-plan quota on a pool. A plan without a row for a pool grants that pool
    # unmetered (when its squad is in the plan) or not at all (when it isn't).
    op.create_table(
        "plan_traffic_pools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pool_id",
            sa.Integer(),
            sa.ForeignKey("traffic_pools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quota_gb", sa.Integer(), nullable=False),
        # The reset period of this quota, configured per plan (a cheap plan may reset
        # monthly while a premium one resets weekly).
        sa.Column("reset_strategy", _STRATEGY, nullable=False, server_default="MONTH"),
        sa.UniqueConstraint("plan_id", "pool_id", name="uq_plan_traffic_pools_plan_pool"),
    )
    op.create_index("ix_plan_traffic_pools_plan_id", "plan_traffic_pools", ["plan_id"])
    op.create_index("ix_plan_traffic_pools_pool_id", "plan_traffic_pools", ["pool_id"])

    # Per-subscription accounting window. One row per (subscription, pool); the row is
    # opened when the subscription first gets the pool and rolls forward in place as
    # periods elapse. It hangs off `subscriptions`, so it travels with the subscription
    # on an account merge and on a plan change (which swaps the subscription row).
    op.create_table(
        "subscription_pool_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pool_id",
            sa.Integer(),
            sa.ForeignKey("traffic_pools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Start of the accounting window currently in force. Derived from the quota's
        # reset strategy; when it moves, the window rolls (counters and notices clear,
        # access is restored).
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        # Bytes observed by the last metering pass. NULL means "below the warning
        # threshold" — the pass filters server-side, so nothing exact is known there.
        sa.Column("used_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_exhausted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exhausted_at", sa.DateTime(timezone=True), nullable=True),
        # Set once per window, so the "почти всё" notice cannot repeat every cron tick.
        sa.Column("warned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metered_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "subscription_id", "pool_id", name="uq_subscription_pool_usage_sub_pool"
        ),
    )
    op.create_index(
        "ix_subscription_pool_usage_pool_id", "subscription_pool_usage", ["pool_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_pool_usage_pool_id", table_name="subscription_pool_usage")
    op.drop_table("subscription_pool_usage")
    op.drop_index("ix_plan_traffic_pools_pool_id", table_name="plan_traffic_pools")
    op.drop_index("ix_plan_traffic_pools_plan_id", table_name="plan_traffic_pools")
    op.drop_table("plan_traffic_pools")
    op.drop_table("traffic_pools")
