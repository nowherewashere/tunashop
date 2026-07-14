from collections.abc import AsyncGenerator

from dishka import Provider, Scope, provide
from loguru import logger
from redis.asyncio import ConnectionPool, Redis

from src.core.config import AppConfig
from src.infrastructure.redis import SupportPubSubRedis

# Shared pool: rate limiter, auth sessions, recent-activity cache, the support
# operator fan-out publish, etc. All quick request/response ops that return their
# connection immediately, so a modest bound is plenty for one app instance.
_SHARED_MAX_CONNECTIONS = 50

# Dedicated support-SSE pool: each open `GET /support/stream` holds ONE pub/sub
# connection here for its whole lifetime. Sized just above the endpoint's global
# stream semaphore (see _MAX_CONCURRENT_STREAMS) so churn — a closing stream
# overlapping a fresh one — still has headroom, while a stream flood exhausts THIS
# pool alone and never starves the shared pool above.
_SUPPORT_PUBSUB_MAX_CONNECTIONS = 220


async def _open_pool(dsn: str, *, max_connections: int, label: str) -> tuple[Redis, ConnectionPool]:
    """Build a bounded Redis client + pool from the single DSN and verify it connects."""
    logger.debug(f"Connecting to Redis ({label}, max_connections={max_connections})")
    pool = ConnectionPool.from_url(
        url=dsn, decode_responses=True, max_connections=max_connections
    )
    client = Redis(connection_pool=pool)
    try:
        await client.ping()  # type: ignore[misc]
        logger.debug(f"Successfully connected to Redis ({label})")
    except Exception as e:
        logger.exception(f"Failed to connect to Redis ({label}): {e}")
        raise
    return client, pool


class RedisProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_redis(self, config: AppConfig) -> AsyncGenerator[Redis, None]:
        client, pool = await _open_pool(
            config.redis.dsn, max_connections=_SHARED_MAX_CONNECTIONS, label="shared"
        )
        yield client
        logger.debug("Closing shared Redis client and disconnecting pool")
        await client.close()
        await pool.disconnect()

    @provide
    async def get_support_pubsub_redis(
        self, config: AppConfig
    ) -> AsyncGenerator[SupportPubSubRedis, None]:
        # Same DSN (single source of truth), separate bounded pool — see the module
        # docstrings above and SupportPubSubRedis. Lazily created: the taskiq worker,
        # which never opens an SSE stream, never resolves this and so never opens it.
        client, pool = await _open_pool(
            config.redis.dsn,
            max_connections=_SUPPORT_PUBSUB_MAX_CONNECTIONS,
            label="support-sse",
        )
        yield SupportPubSubRedis(client)
        logger.debug("Closing support-SSE Redis client and disconnecting pool")
        await client.close()
        await pool.disconnect()
