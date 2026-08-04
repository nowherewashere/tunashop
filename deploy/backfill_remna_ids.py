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

Deliberately standalone and SDK-free: at this point in the rollout the running bot is
still the pre-upgrade image, and the script has to speak the 2.8 API regardless of which
remnapy version happens to be installed.

Usage (from the app host, with the bot's env available):

    python deploy/backfill_remna_ids.py            # resolve and write
    python deploy/backfill_remna_ids.py --dry-run  # report only, touch nothing

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

TIMEOUT = httpx.Timeout(30.0)


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
    host = os.environ["REMNAWAVE_HOST"].rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host


async def _resolve(client: httpx.AsyncClient, uuid: str, username: str) -> Optional[int]:
    """Return the panel's numeric id for a stored uuid, or None if it cannot be found."""
    response = await client.get(f"/api/users/{uuid}")
    if response.status_code == 200:
        payload: dict[str, Any] = response.json()["response"]
        return int(payload["id"])

    if response.status_code != 404:
        response.raise_for_status()

    # The uuid is unknown to the panel — fall back to the username the bot generated.
    # Weaker (see module docstring), so it is only ever a second attempt.
    fallback = await client.get(f"/api/users/by-username/{username}")
    if fallback.status_code == 200:
        payload = fallback.json()["response"]
        return int(payload["id"])

    return None


async def main(dry_run: bool) -> int:
    connection = await asyncpg.connect(_database_dsn())
    try:
        rows = await connection.fetch(
            """
            SELECT s.id, s.user_remna_id::text AS uuid, u.telegram_id, u.id AS user_id
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            WHERE s.user_remna_id_bigint IS NULL
            """
        )
        print(f"{len(rows)} subscription(s) need a panel id")

        if not rows:
            return 0

        headers = {"Authorization": f"Bearer {os.environ['REMNAWAVE_TOKEN']}"}
        resolved = 0
        unresolved: list[str] = []

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
                    panel_id = await _resolve(client, row["uuid"], username)
                except Exception as exception:  # noqa: BLE001 - report and continue
                    print(f"  ! {row['uuid']}: {exception}", file=sys.stderr)
                    unresolved.append(row["uuid"])
                    continue

                if panel_id is None:
                    unresolved.append(row["uuid"])
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

        if unresolved:
            print("\nUnresolved (panel users absent) — retire these before running 0056:")
            for uuid in unresolved:
                print(f"  {uuid}")
            return 1

        return 0
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
