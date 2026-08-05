"""Map every stored Remnawave user UUID to the panel's numeric id.

One-shot migration step for the Remnawave 3.x upgrade. Run it **while the panel is
still on 2.8**, between alembic migrations 0055 and 0056:

    panel 2.8  ->  0055  ->  THIS SCRIPT  ->  upgrade panel to 3.x  ->  0056  ->  bot

Why before the upgrade: on 2.8 a user carries *both* `uuid` and the numeric `id`, and
3.0.0 keeps that same id while dropping the uuid. So asking the 2.8 panel for each
stored uuid yields an exact, unambiguous mapping. After the upgrade the uuids are gone
and the only fallback is matching by username, which the bot itself warns against
(`UserDto.remna_name` is derived, and an account merge can leave it pointing at a panel
user created for a different identity).

Retired rows (`status = DELETED`) are therefore resolved by uuid **only**. Their panel
user is usually gone — an account merge deleted it, an admin did, or the panel itself
did — and the username fallback would then land on a *live* user: after a merge,
`rs_<telegram_id>` resolves to the survivor's panel user, which would stamp a live id
onto a dead row and leave two rows claiming the same panel user. Retired rows that stay
unresolved are reported and left alone; 0056 parks them on panel id 0. A *live* row that
cannot be resolved is a real problem and blocks 0056, so it exits non-zero for those.

Deliberately SDK-free: at this point in the rollout the panel is still on 2.8 while the
image already carries the 3.x-era remnapy, so the 2.8 endpoints are spoken over plain
httpx rather than through whichever SDK version happens to be installed. It does read
`RemnawaveConfig`/`DatabaseConfig` for where the panel and the database are -- see
`_panel_client`.

Usage: run it FROM THE NEW IMAGE, which is the only place its asyncpg/httpx deps and
this file are both present. The container is a toolbox here, not the service -- the bot
itself must not start until the panel is on 3.x and 0056-0058 have run:

    docker run --rm --network remnawave-network --env-file /path/to/.env \
        <new-image> python deploy/backfill_remna_ids.py --dry-run   # touches nothing
    docker run --rm --network remnawave-network --env-file /path/to/.env \
        <new-image> python deploy/backfill_remna_ids.py             # resolve and write

`docker run`, not `docker compose run`: compose would give this throwaway container the
app service's pinned ipv4_address and fail with "Address already in use" while the bot
still holds it. No --entrypoint override is needed either -- the image sets CMD, not
ENTRYPOINT, so a command argument replaces docker-entrypoint.sh (and its unconditional
`alembic upgrade head`, which at this point in the rollout must NOT run).

Environment: the bot's own -- DATABASE_*, REMNAWAVE_HOST, REMNAWAVE_TOKEN -- read
through the app's config objects so there is nothing extra to set. DATABASE_URL
overrides the former when running from outside the container.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Optional

import asyncpg
import httpx

from src.core.config.database import DatabaseConfig
from src.core.config.remnawave import RemnawaveConfig

TIMEOUT = httpx.Timeout(30.0)

# `subscriptions.status` of a retired row (SubscriptionStatus in src/core/enums.py).
RETIRED = "DELETED"


def _database_dsn() -> str:
    """Build the DSN from the bot's own DATABASE_* settings.

    Reuses `DatabaseConfig` for the same reason `_panel_client` reuses
    `RemnawaveConfig`: this script had a second, private idea of the variable names --
    POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB -- that the bot has never set. Those
    are the names the *postgres image* takes in docker-compose, not the ones the app
    reads, so on a real install every run died on `KeyError: 'POSTGRES_USER'` before
    opening a single connection.

    DATABASE_URL still wins when present: it is the escape hatch for driving this from
    outside the container, e.g. over a tunnelled port from a bastion.
    """
    if dsn := os.getenv("DATABASE_URL"):
        return dsn.replace("postgresql+asyncpg://", "postgresql://")

    return DatabaseConfig().dsn.replace("postgresql+asyncpg://", "postgresql://")


def _panel_client() -> httpx.AsyncClient:
    """Aim a client at the panel exactly the way the running bot aims one.

    Both halves of this were wrong while written out by hand here, and neither failed in
    a way that pointed at itself:

    * `RemnawaveConfig.url` appends :3000 to a portless http host and promotes a bare
      domain to https. Prepending "http://" and stopping -- what this did -- sent
      REMNAWAVE_HOST=remnawave, the .env.example default, to port 80.
    * `client_headers` carries the x-forwarded-* pair an internal panel demands. Without
      it the panel closes the connection and httpx raises RemoteProtocolError.

    Either way every request raises, so the run still *finishes* and files all nine rows
    as unresolved: live ones look corrupt, retired ones look like their panel user is
    gone. Reading the config instead of paraphrasing it is what stops that recurring.
    """
    config = RemnawaveConfig()
    return httpx.AsyncClient(
        base_url=config.url.get_secret_value(),
        headers=config.client_headers,
        cookies=config.cookies,
        timeout=TIMEOUT,
    )


async def _resolve(
    client: httpx.AsyncClient,
    uuid: str,
    username: str,
    *,
    allow_username_fallback: bool,
) -> Optional[int]:
    """Return the panel's numeric id for a stored uuid, or None if it cannot be found."""
    response = await client.get(f"/api/users/{uuid}")
    if response.status_code == 200:
        payload: dict[str, Any] = response.json()["response"]
        return int(payload["id"])

    if response.status_code != 404:
        response.raise_for_status()

    if not allow_username_fallback:
        return None

    # The uuid is unknown to the panel — fall back to the username the bot generated.
    # Weaker (see module docstring), so it is only ever a second attempt.
    fallback = await client.get(f"/api/users/by-username/{username}")
    if fallback.status_code == 200:
        payload = fallback.json()["response"]
        return int(payload["id"])

    return None


def _describe(row: asyncpg.Record) -> str:
    """One unresolved row, in terms an operator can act on — the uuid alone is useless."""
    return (
        f"{row['uuid']}  subscription={row['id']} user={row['user_id']} "
        f"telegram={row['telegram_id']} status={row['status']}"
    )


def _report(missing: list[asyncpg.Record], errored: list[asyncpg.Record]) -> int:
    """Print the leftovers, split by what they mean, and return the process exit code.

    `missing` is an answer from the panel: it looked and has no such user. For a retired
    row that is the expected end state of a merge or a delete, so 0056 parks it on panel
    id 0 and carries on; for a live row it is a real problem that 0056 must refuse until
    a human deals with it, while the uuid is still there to look at.

    `errored` is the absence of an answer -- a timeout, a refused connection, a 502 from
    something in front of the panel. It is never evidence about the panel user, so it
    can never be filed as "no panel user left". Conflating the two is unrecoverable
    rather than merely wrong: 0056 would park a retired row whose panel user is alive on
    the sentinel and then drop `user_remna_id`, destroying the only copy of the mapping.
    A blip on one row therefore fails the whole step, which is the cheap direction.
    """
    gone = [row for row in missing if row["status"] == RETIRED]
    blocking = [row for row in missing if row["status"] != RETIRED]

    if gone:
        print(
            f"\n{len(gone)} retired subscription(s) have no panel user left "
            "(expected — 0056 parks these on panel id 0):\n"
            + "\n".join(f"  {_describe(row)}" for row in gone)
        )

    if errored:
        print(
            f"\n{len(errored)} subscription(s) could not be CHECKED — the panel never "
            "answered, so nothing is known about them. Fix the connection and re-run; "
            "do NOT proceed to 0056:\n" + "\n".join(f"  {_describe(row)}" for row in errored)
        )

    if blocking:
        print(
            f"\n{len(blocking)} LIVE subscription(s) could not be resolved — retire or "
            "fix these before running 0056:\n"
            + "\n".join(f"  {_describe(row)}" for row in blocking)
        )

    return 1 if (blocking or errored) else 0


async def main(dry_run: bool) -> int:
    connection = await asyncpg.connect(_database_dsn())
    try:
        rows = await connection.fetch(
            """
            SELECT s.id, s.user_remna_id::text AS uuid, s.status::text AS status,
                   u.id AS user_id, u.telegram_id
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            WHERE s.user_remna_id_bigint IS NULL
            ORDER BY s.id
            """
        )
        print(f"{len(rows)} subscription(s) need a panel id")

        if not rows:
            return 0

        resolved = 0
        missing: list[asyncpg.Record] = []  # the panel answered: no such user
        errored: list[asyncpg.Record] = []  # the panel did not answer at all

        async with _panel_client() as client:
            for row in rows:
                # Mirrors UserDto.remna_name (REMNASHOP_PREFIX / WEB_PREFIX in
                # src/core/constants.py): telegram users are rs_<tg_id>, web-only
                # users rs_web_<user_id>.
                username = (
                    f"rs_{row['telegram_id']}"
                    if row["telegram_id"] is not None
                    else f"rs_web_{row['user_id']}"
                )

                try:
                    panel_id = await _resolve(
                        client,
                        row["uuid"],
                        username,
                        # A retired row's panel user is gone, so a username hit can only
                        # be somebody else's live user — see the module docstring.
                        allow_username_fallback=row["status"] != RETIRED,
                    )
                except Exception as exception:  # noqa: BLE001 - report and continue
                    print(f"  ! {_describe(row)}: {exception}", file=sys.stderr)
                    errored.append(row)
                    continue

                if panel_id is None:
                    missing.append(row)
                    continue

                if not dry_run:
                    await connection.execute(
                        "UPDATE subscriptions SET user_remna_id_bigint = $1 WHERE id = $2",
                        panel_id,
                        row["id"],
                    )
                resolved += 1

        verb = "would resolve" if dry_run else "resolved"
        print(f"{verb} {resolved}, no such panel user {len(missing)}, unreachable {len(errored)}")

        return _report(missing, errored)
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be resolved without writing anything",
    )
    raise SystemExit(asyncio.run(main(parser.parse_args().dry_run)))
