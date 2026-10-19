"""Lazy async Redis client shared by the rate limiter and cache."""

from typing import Optional

import redis.asyncio as aioredis

from lunair.config import settings

_client: Optional[aioredis.Redis] = None


async def get_redis() -> Optional[aioredis.Redis]:
    """Return a shared Redis client, or None if it cannot be constructed."""
    global _client
    if _client is None:
        try:
            _client = aioredis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        except Exception:
            return None
    return _client


async def redis_available() -> bool:
    client = await get_redis()
    if client is None:
        return False
    try:
        await client.ping()
        return True
    except Exception:
        return False
