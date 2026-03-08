"""Redis cache layer for API key lookups (SaaS mode).

Caches validated key results to avoid hitting PostgreSQL on every ingest request.
Degrades gracefully — Redis failures are logged but never block requests.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("argus.auth.key_cache")

_redis: Any = None  # redis.asyncio.Redis instance

# Cache TTLs
_VALID_TTL = 300    # 5 minutes for valid keys
_INVALID_TTL = 60   # 1 minute for invalid lookups


async def init_key_cache(redis_url: str) -> None:
    """Initialize the Redis connection for key caching."""
    global _redis
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(redis_url, decode_responses=True)
        # Test connectivity
        await _redis.ping()
        logger.info("Redis key cache initialized at %s", redis_url.split("@")[-1])
    except Exception:
        logger.warning("Redis key cache initialization failed (degraded mode)", exc_info=True)
        _redis = None


async def close_key_cache() -> None:
    """Close the Redis connection."""
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None


async def get_cached_key(key_hash: str) -> dict[str, Any] | None:
    """Look up a key validation result from cache.

    Returns:
        The cached result dict on cache hit, ``None`` on miss or error.
    """
    if _redis is None:
        return None
    try:
        raw = await _redis.get(f"apikey:{key_hash}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.debug("Redis cache read failed", exc_info=True)
        return None


async def cache_key_result(key_hash: str, result: dict[str, Any] | None) -> None:
    """Cache a key validation result.

    Valid results are cached for 5 minutes, invalid (None) for 1 minute.
    """
    if _redis is None:
        return
    try:
        cache_key = f"apikey:{key_hash}"
        if result is not None:
            await _redis.setex(cache_key, _VALID_TTL, json.dumps(result))
        else:
            # Cache "invalid" as a sentinel to avoid repeated DB lookups
            await _redis.setex(cache_key, _INVALID_TTL, json.dumps({"_invalid": True}))
    except Exception:
        logger.debug("Redis cache write failed", exc_info=True)


async def invalidate_key(key_hash: str) -> None:
    """Remove a key from the cache (e.g., after revocation)."""
    if _redis is None:
        return
    try:
        await _redis.delete(f"apikey:{key_hash}")
    except Exception:
        logger.debug("Redis cache delete failed", exc_info=True)
