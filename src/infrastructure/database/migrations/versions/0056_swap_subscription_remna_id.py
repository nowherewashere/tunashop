import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger("alembic.runtime.migration")

# A retired row's panel user is usually gone (account merge, admin delete, panel-side
# delete), so there is no id left to resolve. 0 is the sentinel for that: panel ids are
# a positive sequence, so no webhook can ever match a row parked here.
NO_PANEL_USER = 0

# What `events.user_ref` looked like before the cutover: str(UUID). Matches exactly the
# rows the remap below could not translate.
UUID_REF = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# Every uuid -> panel id pair still derivable. Both columns sit on `subscriptions` only
# between 0055 and the drop below, so this CTE is the entire window in which the
# translation exists at all. `min()` breaks a tie that cannot happen (one panel user =
# one uuid = one id); it is there so the statement is deterministic rather than letting
# the planner pick whichever duplicate row it reaches first.
REMAP_CTE = """
    WITH remap AS (
        SELECT user_remna_id::text AS old_ref,
               min(user_remna_id_bigint)::text AS new_ref
        FROM subscriptions
        WHERE user_remna_id_bigint IS NOT NULL
        GROUP BY user_remna_id
    )
"""


def upgrade() -> None:
    # Second half of the UUID -> BigInt swap opened by 0055. Run this only after
    # `deploy/backfill_remna_ids.py` has resolved every LIVE row against the panel,
    # otherwise the guard below trips — which is the intended safety net, not a bug.
    #
    # The guard deliberately ignores retired (DELETED) rows. Their panel user is gone
    # by definition, so the backfill cannot resolve them and refuses to guess: matching
    # by username would resolve a merged account's retired row onto the SURVIVOR's live
    # panel user, stamping a live id onto a dead row. They are parked on
    # `NO_PANEL_USER` further down instead of blocking the whole rollout.
    connection = op.get_bind()
    unresolved = connection.execute(
        sa.text(
            "SELECT count(*) FROM subscriptions "
            "WHERE user_remna_id_bigint IS NULL AND status <> 'DELETED'"
        )
    ).scalar_one()
    if unresolved:
        raise RuntimeError(
            f"{unresolved} live subscription(s) still have no panel id. "
            "Run `python deploy/backfill_remna_ids.py` first (before the panel "
            "upgrade); it lists every row it could not resolve with its id, owner and "
            "status. A live subscription the panel has never heard of has to be "
            "retired by hand before this migration can proceed — already-retired rows "
            "are handled automatically."
        )

    _remap_event_refs(connection)

    # After the guard, the only rows that can still be NULL are retired ones. Park them
    # so the NOT NULL below can land. Strictly AFTER the remap, which must read real
    # pairs and never see the sentinel.
    parked = connection.execute(
        sa.text(
            "UPDATE subscriptions SET user_remna_id_bigint = :sentinel "
            "WHERE user_remna_id_bigint IS NULL"
        ),
        {"sentinel": NO_PANEL_USER},
    ).rowcount
    if parked:
        log.info(
            f"0056: parked {parked} retired subscription(s) on panel id {NO_PANEL_USER} "
            f"— their panel user is gone, so nothing can resolve onto them"
        )

    op.drop_index("ix_subscriptions_user_remna_id", table_name="subscriptions")
    op.drop_column("subscriptions", "user_remna_id")

    op.alter_column(
        "subscriptions",
        "user_remna_id_bigint",
        new_column_name="user_remna_id",
        nullable=False,
    )
    op.drop_index("ix_subscriptions_user_remna_id_bigint", table_name="subscriptions")
    op.create_index("ix_subscriptions_user_remna_id", "subscriptions", ["user_remna_id"])


def _remap_event_refs(connection: sa.Connection) -> None:
    """Carry the metrics store over to the new identifier space, while it is still possible.

    Every per-user row in `events` is keyed on `str(subscription.user_remna_id)`
    (metrics spec §3): a UUID string for everything written before the panel upgrade, a
    numeric id for everything after. Left alone, one person's history splits into two
    unrelated users at the cutover — `EventsDaoImpl.lifetime_days` joins first_connect
    to churned on `user_ref`, and the "first payment ever?" check in
    `MetricsEventListener.on_payment` would read a long-standing payer as a new one.

    `properties->>'referrer_ref'` holds the same kind of value, so it moves with it —
    scoped to `referral_attributed`, the only event type that carries the key. The
    literal is frozen here rather than imported from `core.metrics`: a migration must
    describe the rows as they were, not follow an enum that can drift under it.

    Partial by nature: a panel user whose subscription row no longer exists contributes
    no pair, so its events keep their UUID and stay a separate series. Analytics must
    not be able to block a schema migration, so that is counted and logged, never raised.
    """
    refs = connection.execute(
        sa.text(
            REMAP_CTE
            + """
            UPDATE events e
            SET user_ref = remap.new_ref
            FROM remap
            WHERE e.user_ref = remap.old_ref
            """
        )
    ).rowcount

    referrers = connection.execute(
        sa.text(
            REMAP_CTE
            + """
            UPDATE events e
            SET properties = jsonb_set(
                e.properties, '{referrer_ref}', to_jsonb(remap.new_ref)
            )
            FROM remap
            WHERE e.event_type = 'referral_attributed'
              AND e.properties->>'referrer_ref' = remap.old_ref
            """
        )
    ).rowcount
    log.info(f"0056: remapped {refs} event user_ref(s) and {referrers} referrer_ref(s)")

    stranded = connection.execute(
        sa.text("SELECT count(*) FROM events WHERE user_ref ~* :uuid_ref"),
        {"uuid_ref": UUID_REF},
    ).scalar_one()
    if stranded:
        log.warning(
            f"0056: {stranded} event(s) keep a UUID user_ref — the panel user they "
            f"belong to has no subscription row left to map from, so their history "
            f"stays a separate series"
        )


def downgrade() -> None:
    # The original UUIDs are gone for good once 0055's source column is dropped, so this
    # only restores the shape — the values cannot come back, and `events.user_ref` stays
    # numeric for the same reason.
    op.drop_index("ix_subscriptions_user_remna_id", table_name="subscriptions")
    op.alter_column(
        "subscriptions",
        "user_remna_id",
        new_column_name="user_remna_id_bigint",
        nullable=True,
    )
    op.create_index(
        "ix_subscriptions_user_remna_id_bigint",
        "subscriptions",
        ["user_remna_id_bigint"],
    )
    # 0003 declared this column NOT NULL, so restore it that way. The default exists
    # only to satisfy NOT NULL on a populated table and is dropped again immediately,
    # leaving exactly the original shape; the values it writes are placeholders.
    op.add_column(
        "subscriptions",
        sa.Column(
            "user_remna_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.alter_column("subscriptions", "user_remna_id", server_default=None)
    op.create_index("ix_subscriptions_user_remna_id", "subscriptions", ["user_remna_id"])
