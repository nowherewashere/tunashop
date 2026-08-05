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
`RemnawaveConfig` for the panel URL -- see `_panel_base_url`.

Usage: run it FROM THE NEW IMAGE, which is the only place its asyncpg/httpx deps and
this file are both present. The container is a toolbox here, not the service -- the bot
itself must not start until the panel is on 3.x and 0056-0058 have run:

    docker compose run --rm --no-deps --entrypoint "" app \
        python deploy/backfill_remna_ids.py --dry-run   # report only, touch nothing
    docker compose run --rm --no-deps --entrypoint "" app \
        python deploy/backfill_remna_ids.py             # resolve and write

Environment: POSTGRES_* (or DATABASE_URL), REMNAWAVE_HOST, REMNAWAVE_TOKEN.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Optional

import asyncpg
import httpx
from pydantic import SecretStr

from src.core.config.remnawave import RemnawaveConfig

TIMEOUT = httpx.Timeout(30.0)

# `subscriptions.status` of a retired row (SubscriptionStatus in src/core/enums.py).
RETIRED = "DELETED"


def _database_dsn() -> str:
    if dsn := os.getenv("DATABASE_URL"):
        return dsn.replace("postgresql+asyncpg://", "postgresql://")

    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.environ["POSTGRES_DB"]
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _panel_base_url() -> str:
    """Resolve REMNAWAVE_HOST exactly the way the running bot does.

    Delegates to `RemnawaveConfig.url` instead of re-deriving, because the two silently
    disagreed on the most common settings: a bare `remnawave` means port **3000**, not
    80, and a bare domain means **https**, not http. Getting either wrong does not fail
    loudly here -- every request just raises ConnectError, every row is filed unresolved,
    and the run ends with "0 resolved" and a list of live rows that look corrupt but are
    only unreachable.

    `model_construct` skips validation on purpose: only `host` participates in the URL,
    and this script must not start requiring REMNAWAVE_TOKEN's neighbours (webhook
    secret et al) just to compute a base URL.
    """
    config = RemnawaveConfig.model_construct(host=SecretStr(os.environ["REMNAWAVE_HOST"]))
    return config.url.get_secret_value()


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


def _report(unresolved: list[asyncpg.Record]) -> int:
    """Print the leftovers, split by what they mean, and return the process exit code.

    A retired row with no panel user left is the expected end state of a merge or a
    delete, not an error: 0056 parks it on panel id 0 and carries on. Anything else is a
    live subscription the panel has never heard of, and 0056 will refuse to run until it
    is dealt with — by hand, while the uuid is still there to look at.
    """
    retired = [row for row in unresolved if row["status"] == RETIRED]
    blocking = [row for row in unresolved if row["status"] != RETIRED]

    if retired:
        print(
            f"\n{len(retired)} retired subscription(s) have no panel user left "
            "(expected — 0056 parks these on panel id 0):\n"
            + "\n".join(f"  {_describe(row)}" for row in retired)
        )

    if blocking:
        print(
            f"\n{len(blocking)} LIVE subscription(s) could not be resolved — retire or "
            "fix these before running 0056:\n"
            + "\n".join(f"  {_describe(row)}" for row in blocking)
        )
        return 1

    return 0


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

        headers = {"Authorization": f"Bearer {os.environ['REMNAWAVE_TOKEN']}"}
        resolved = 0
        unresolved: list[asyncpg.Record] = []

        async with httpx.AsyncClient(
            base_url=_panel_base_url(), headers=headers, timeout=TIMEOUT
        ) as client:
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
                    unresolved.append(row)
                    continue

                if panel_id is None:
                    unresolved.append(row)
                    continue

                if not dry_run:
                    await connection.execute(
                        "UPDATE subscriptions SET user_remna_id_bigint = $1 WHERE id = $2",
                        panel_id,
                        row["id"],
                    )
                resolved += 1

        verb = "would resolve" if dry_run else "resolved"
        print(f"{verb} {resolved}, unresolved {len(unresolved)}")

        return _report(unresolved)
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
