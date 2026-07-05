import re
from typing import Final, Optional

import orjson
from adaptix import Retort
from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from packaging.version import InvalidVersion, Version
from redis.asyncio import Redis

from src.application.common import EventPublisher
from src.application.events import BotUpdateEvent
from src.core.config import AppConfig
from src.infrastructure.redis.keys import LatestNotifiedVersionKey
from src.infrastructure.taskiq.broker import broker

GITHUB_RELEASE_URL: Final[str] = "https://api.github.com/repos/snoups/remnashop/releases/latest"


def _parse_version(raw: str) -> Optional[Version]:
    """Parse a release tag into a comparable Version, tolerating fork tags.

    Fork releases carry a non-PEP 440 suffix (e.g. ``0.8.2-tuna.1``) that
    ``Version()`` rejects outright. We compare against the upstream base version
    we're derived from, so strip any ``-``/``+`` suffix before parsing and never
    let a malformed tag bubble an exception up into the worker.
    """
    for candidate in (raw, re.split(r"[-+]", raw, maxsplit=1)[0]):
        try:
            return Version(candidate)
        except InvalidVersion:
            continue
    return None


@broker.task(schedule=[{"cron": "0 * * * *"}], retry_on_error=False)
@inject(patch_module=True)
async def check_bot_update(
    config: FromDishka[AppConfig],
    retort: FromDishka[Retort],
    redis: FromDishka[Redis],
    event_publisher: FromDishka[EventPublisher],
) -> None:
    if not config.build.tag or config.build.tag == "dev":
        logger.debug("Local version is a development build, skipping update check")
        return

    local_version = config.build.tag.replace("v", "") if config.build.tag else None

    if not local_version:
        logger.warning("Local version tag is missing in config, skipping update check")
        return

    import httpx  # noqa: PLC0415

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=30.0,
                write=10.0,
                pool=5.0,
            )
        ) as client:
            headers = {"Accept": "application/vnd.github.v3+json"}
            response = await client.get(GITHUB_RELEASE_URL, headers=headers)
            response.raise_for_status()

            data = orjson.loads(response.content)
            remote_version = data.get("tag_name", "").replace("v", "")

            if not remote_version:
                logger.error("Remote version tag not found in GitHub API response")
                return
    except httpx.ConnectError as e:
        logger.warning(f"Failed to reach GitHub API (network issue): '{e}'")
        return
    except httpx.TimeoutException as e:
        logger.warning(f"GitHub API request timed out: '{e}'")
        return
    except httpx.HTTPStatusError as e:
        logger.warning(f"GitHub API returned error status: '{e}'")
        return

    lv = _parse_version(local_version)
    rv = _parse_version(remote_version)

    if lv is None or rv is None:
        logger.warning(
            f"Skipping update check: unparseable version "
            f"(local='{local_version}', remote='{remote_version}')"
        )
        return

    if rv <= lv:
        status = "up to date" if rv == lv else "ahead of remote"
        logger.debug(f"Project is '{status}': '{local_version}'")
        return

    key = retort.dump(LatestNotifiedVersionKey(version="*"))
    last_notified_version = await redis.get(key)

    logger.debug(
        f"Update check: key='{key}', cached={last_notified_version!r}, remote={remote_version!r}"
    )

    if last_notified_version == remote_version:
        logger.debug(f"Version '{remote_version}' already notified")
        return

    await redis.set(key, value=remote_version)
    logger.info(f"New version available: '{remote_version}' (local: '{local_version}')")

    event = BotUpdateEvent(local_version=local_version, remote_version=remote_version)
    await event_publisher.publish(event)
