from typing import Optional, cast

from redis.asyncio import Redis

from src.application.common.dao.bot_login import BotLoginRequest, BotLoginStatus
from src.infrastructure.redis.key_builder import serialize_storage_key
from src.infrastructure.redis.keys import BotLoginKey

# Resolve only a request that is still pending, in one round trip. A plain
# read-then-write would let two people who both hold the token (one having read the QR
# off a screen) race, with the loser's decision silently overwriting the winner's.
# HSET on an existing key preserves its TTL, so the expiry still stands.
_RESOLVE = """
if redis.call('HGET', KEYS[1], 'status') ~= 'pending' then return 0 end
redis.call('HSET', KEYS[1], 'status', ARGV[1], 'user_id', ARGV[2])
return 1
"""

# Read and delete together, so a session can be claimed exactly once.
_CONSUME = """
local values = redis.call('HGETALL', KEYS[1])
if #values == 0 then return nil end
redis.call('DEL', KEYS[1])
return values
"""


class RedisBotLoginRepository:
    """Pending "confirm this sign-in in the bot" handshakes.

    Stored as a hash rather than a JSON blob so the status transition can be made
    conditional inside Redis instead of in application code.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._resolve = redis.register_script(_RESOLVE)
        self._consume = redis.register_script(_CONSUME)

    async def put(self, token: str, value: BotLoginRequest, ttl: int) -> None:
        key = serialize_storage_key(BotLoginKey(token=token))
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(
                key,
                mapping={
                    "status": value.status,
                    "binding_hash": value.binding_hash,
                    "ip": value.ip or "",
                    "user_id": "" if value.user_id is None else str(value.user_id),
                },
            )
            pipe.expire(key, ttl)
            await pipe.execute()

    async def get(self, token: str) -> Optional[BotLoginRequest]:
        raw = await self.redis.hgetall(  # type: ignore[misc]
            serialize_storage_key(BotLoginKey(token=token))
        )
        return _to_request(raw) if raw else None

    async def resolve(self, token: str, status: BotLoginStatus, user_id: Optional[int]) -> bool:
        changed = await self._resolve(
            keys=[serialize_storage_key(BotLoginKey(token=token))],
            args=[status, "" if user_id is None else str(user_id)],
        )
        return bool(changed)

    async def consume(self, token: str) -> Optional[BotLoginRequest]:
        values = await self._consume(keys=[serialize_storage_key(BotLoginKey(token=token))])
        if not values:
            return None
        flat = cast(list, values)
        raw = {_decode(flat[i]): _decode(flat[i + 1]) for i in range(0, len(flat) - 1, 2)}
        return _to_request(raw)


def _decode(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _to_request(raw: dict) -> BotLoginRequest:
    data = {_decode(k): _decode(v) for k, v in raw.items()}
    user_id = data.get("user_id") or ""
    return BotLoginRequest(
        status=cast(BotLoginStatus, data.get("status", "pending")),
        binding_hash=data.get("binding_hash", ""),
        ip=data.get("ip") or None,
        user_id=int(user_id) if user_id else None,
    )
