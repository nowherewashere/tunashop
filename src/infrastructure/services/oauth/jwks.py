import asyncio
import time
from typing import Optional

import jwt
from loguru import logger

from src.core.exceptions import OAuthExchangeError

from .base import get_json

# Signing keys rotate on the order of days; refetching a few times a day is ample.
_DEFAULT_TTL_SECONDS = 6 * 60 * 60
# Floor between forced refetches. Without it, a token carrying an unknown `kid` is a
# free JWKS fetch, and a stream of them turns into an amplification channel at the
# provider's expense (and ours).
_MIN_REFRESH_INTERVAL_SECONDS = 300


class JwksCache:
    """Caches a provider's JSON Web Key Set for id_token signature verification.

    pyjwt ships ``PyJWKClient``, but it fetches over synchronous ``urllib`` — calling
    it from the event loop would stall every other request on the worker. So: fetch
    with aiohttp, hand the document to pyjwt to parse.

    In-process, since each container runs one app and a cache miss costs one HTTPS
    request. Redis would buy cross-process sharing for a value that is already cheap
    to obtain and identical everywhere.
    """

    def __init__(
        self,
        jwks_url: str,
        timeout: int,
        ttl: int = _DEFAULT_TTL_SECONDS,
        min_refresh_interval: int = _MIN_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        self._url = jwks_url
        self._timeout = timeout
        self._ttl = ttl
        self._min_refresh_interval = min_refresh_interval
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> jwt.PyJWK:
        key = await self._lookup(kid, force=False)
        if key is not None:
            return key
        # Unknown kid: either the set is stale (a genuine rotation) or the token is
        # forged. One bounded refetch distinguishes them.
        key = await self._lookup(kid, force=True)
        if key is None:
            raise OAuthExchangeError(f"no signing key for kid '{kid}'")
        return key

    async def _lookup(self, kid: str, force: bool) -> Optional[jwt.PyJWK]:
        async with self._lock:
            age = time.monotonic() - self._fetched_at
            stale = age >= self._ttl
            may_force = force and age >= self._min_refresh_interval
            if not self._keys or stale or may_force:
                await self._refresh()
            return self._keys.get(kid)

    async def _refresh(self) -> None:
        payload = await get_json(self._url, headers={}, timeout=self._timeout)
        try:
            key_set = jwt.PyJWKSet.from_dict(payload)
        except jwt.PyJWKSetError as e:
            raise OAuthExchangeError(f"malformed JWKS from {self._url}: {e}") from e

        keys = {key.key_id: key for key in key_set.keys if key.key_id}
        if not keys:
            raise OAuthExchangeError(f"JWKS from {self._url} carries no usable keys")

        self._keys = keys
        self._fetched_at = time.monotonic()
        logger.debug(f"Refreshed JWKS from {self._url}: {len(keys)} key(s)")
