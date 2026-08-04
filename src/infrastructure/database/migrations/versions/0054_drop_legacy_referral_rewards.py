from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Retire the pre-0045 points / extra-days referral engine.

    The money rework (0045) replaced ``AssignReferralRewards`` with
    ``RecordReferralCommission`` but left the old storage in place: nothing has written
    ``referral_rewards`` or ``users.points`` since, and the admin screens that read them
    showed permanently frozen numbers. The attribution table ``referrals`` and the
    ``referral_level`` enum stay — they are still written by ``AttachReferral``.
    """
    op.drop_table("referral_rewards")

    # referral_reward_type was created by 0013 for referral_rewards.type. The other two
    # only ever existed in the SQLAlchemy type map (the settings blob stored them as
    # plain JSON), so they may have no PG type at all — hence IF EXISTS.
    # referral_level stays: it is still live on referrals.level.
    op.execute("DROP TYPE IF EXISTS referral_reward_type")
    op.execute("DROP TYPE IF EXISTS referral_accrual_strategy")
    op.execute("DROP TYPE IF EXISTS referral_reward_strategy")

    # settings.referral keeps only the runtime switch. The retort loader skips extra
    # keys (ExtraSkip), so this is hygiene rather than a hard prerequisite for the code.
    op.execute(
        """
        UPDATE settings
        SET referral = jsonb_build_object(
            'enable', COALESCE(referral -> 'enable', 'true'::jsonb)
        )
        """
    )

    op.drop_column("users", "points")


def downgrade() -> None:
    """Restores the structure, not the data.

    Reward rows, the points balances and the old settings sub-keys are gone for good;
    this only puts the schema back so an older revision can boot.
    """
    op.add_column(
        "users",
        sa.Column("points", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # Only this one was ever a real PG type (0013); the strategy enums lived in JSON.
    # create_table emits the CREATE TYPE inline, same as 0013 did.
    reward_type = sa.Enum("POINTS", "EXTRA_DAYS", name="referral_reward_type")

    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referral_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", reward_type, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("is_issued", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["referral_id"], ["referrals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_referral_rewards_referral_id"),
        "referral_rewards",
        ["referral_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_referral_rewards_user_id"),
        "referral_rewards",
        ["user_id"],
        unique=False,
    )

    op.execute(
        """
        UPDATE settings
        SET referral = referral || jsonb_build_object(
            'level', 1,
            'accrual_strategy', 'ON_FIRST_PAYMENT',
            'reward', jsonb_build_object(
                'type', 'EXTRA_DAYS',
                'strategy', 'AMOUNT',
                'config', jsonb_build_object('1', 5)
            )
        )
        """
    )
