import hashlib

from redis.asyncio import Redis

from src.infrastructure.redis.key_builder import serialize_storage_key
from src.infrastructure.redis.keys import RateLimitKey


class RedisRateLimiter:
    """Fixed-window rate limiter backed by Redis (INCR + EXPIRE NX).

    The identifier is hashed, so raw values (e.g. emails) are never stored as keys.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def hit(
        self,
        scope: str,
        identifier: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> bool:
        key = serialize_storage_key(RateLimitKey(scope=scope, identifier=self._digest(identifier)))
        count = int(await self.redis.incr(key))
        # Set the window TTL only on the first hit so the window stays fixed.
        await self.redis.expire(key, window_seconds, nx=True)
        return count <= limit

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
