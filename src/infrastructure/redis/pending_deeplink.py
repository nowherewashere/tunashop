from typing import Optional

from redis.asyncio import Redis

from src.infrastructure.redis.key_builder import serialize_storage_key
from src.infrastructure.redis.keys import PendingDeeplinkKey

# Claim the parked link only if it is the caller's own flow, in one round trip. Two
# quick taps on "принимаю" would otherwise both read it and both resume the flow.
_TAKE = """
local value = redis.call('GET', KEYS[1])
if not value then return nil end
if string.sub(value, 1, string.len(ARGV[1])) ~= ARGV[1] then return nil end
redis.call('DEL', KEYS[1])
return value
"""


class RedisPendingDeeplinkRepository:
    """Deep links parked by a gate, keyed by the Telegram user who opened them."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._take = redis.register_script(_TAKE)

    async def remember(self, telegram_id: int, payload: str, ttl: int) -> None:
        await self.redis.setex(self._key(telegram_id), ttl, payload)

    async def take(self, telegram_id: int, prefix: str) -> Optional[str]:
        value = await self._take(keys=[self._key(telegram_id)], args=[prefix])
        if value is None:
            return None
        payload = value.decode() if isinstance(value, bytes) else str(value)
        return payload[len(prefix) :]

    @staticmethod
    def _key(telegram_id: int) -> str:
        return serialize_storage_key(PendingDeeplinkKey(telegram_id=telegram_id))
