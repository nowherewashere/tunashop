import json
from typing import Optional, cast

from loguru import logger
from redis.asyncio import Redis

from src.application.common.dao.oauth_state import OAuthFlowMode, OAuthFlowState
from src.core.enums import OAuthProvider
from src.infrastructure.redis.key_builder import serialize_storage_key
from src.infrastructure.redis.keys import OAuthStateKey


class RedisOAuthStateRepository:
    """In-flight OAuth flows, keyed by their CSRF state.

    Redis rather than the database because the record lives for minutes, is written
    on every sign-in attempt, and must vanish on its own if the user abandons the
    consent screen — a TTL does that for free where a table would need sweeping.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def put(self, state: str, value: OAuthFlowState, ttl: int) -> None:
        payload = json.dumps(
            {
                "provider": value.provider.value,
                "mode": value.mode,
                "code_verifier": value.code_verifier,
                "binding_hash": value.binding_hash,
                "referral_code": value.referral_code,
                "actor_user_id": value.actor_user_id,
            }
        )
        await self.redis.setex(serialize_storage_key(OAuthStateKey(state=state)), ttl, payload)

    async def consume(self, state: str) -> Optional[OAuthFlowState]:
        # GETDEL, the same primitive that makes refresh tokens single-use
        # (RedisAuthRepository.get_and_revoke_refresh_token): read and delete are one
        # atomic step, so two concurrent callbacks cannot both win.
        raw = await self.redis.getdel(serialize_storage_key(OAuthStateKey(state=state)))
        if raw is None:
            return None

        try:
            data = json.loads(raw)
            return OAuthFlowState(
                provider=OAuthProvider(data["provider"]),
                mode=cast(OAuthFlowMode, data["mode"]),
                code_verifier=data["code_verifier"],
                binding_hash=data["binding_hash"],
                referral_code=data["referral_code"],
                actor_user_id=data["actor_user_id"],
            )
        except (ValueError, KeyError, TypeError) as e:
            # A malformed blob means a shape change mid-deploy or a corrupted key. The
            # state is already deleted, so the caller just sees an invalid flow and the
            # user retries — which is the correct outcome either way.
            logger.warning(f"Discarded unreadable OAuth state: {e}")
            return None
