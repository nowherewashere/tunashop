import hashlib
from typing import Optional

from redis.asyncio import Redis

from src.infrastructure.redis.key_builder import serialize_storage_key
from src.infrastructure.redis.keys import EmailLoginLinkKey


class RedisEmailLoginLinkRepository:
    """Magic-link tokens, keyed by their hash.

    The token itself is never stored: it travels in an email, so anyone who could read
    these keys would otherwise be able to sign in as any user who had one outstanding —
    the same reason a password is not stored in the clear.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def put(self, token: str, email: str, ttl: int) -> None:
        await self.redis.setex(self._key(token), ttl, email)

    async def consume(self, token: str) -> Optional[str]:
        # GETDEL — read and delete atomically, so a link works exactly once even if it
        # is opened twice in quick succession.
        value = await self.redis.getdel(self._key(token))
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    @staticmethod
    def _key(token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return serialize_storage_key(EmailLoginLinkKey(token_hash=digest))
