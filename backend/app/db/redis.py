from functools import lru_cache

import redis

from app.core.config import settings


@lru_cache
def get_redis() -> redis.Redis | None:
    """Return a lazily connected Redis client. Connection errors are handled by callers."""
    try:
        return redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
        )
    except (redis.RedisError, ValueError):
        return None
