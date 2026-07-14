from typing import NewType

from redis.asyncio import Redis

# A Redis client whose connection pool is dedicated to the support SSE streams
# (`GET /api/v1/public/support/stream`). Each open stream holds ONE pub/sub connection
# from this pool for its whole lifetime, so a flood of long-lived streams can exhaust
# only THIS pool — never the shared `Redis` pool that the rate limiter and the operator
# fan-out publish depend on. Provided by ``RedisProvider`` and injected by the SSE
# endpoint; distinct from ``Redis`` purely so dishka hands out the right client.
SupportPubSubRedis = NewType("SupportPubSubRedis", Redis)

__all__ = ["SupportPubSubRedis"]
