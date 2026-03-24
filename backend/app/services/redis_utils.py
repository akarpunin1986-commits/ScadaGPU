"""Redis singleton utility."""
from __future__ import annotations

_redis_client = None


async def _get_redis():
    """Lazy Redis singleton."""
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import Redis as AioRedis
        from config import settings
        _redis_client = AioRedis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


# Public alias
get_redis = _get_redis
