"""
JSON cache on Redis with a process-local fallback.

Redis being down must never break a request: on any Redis error the call falls
back to a bounded in-memory dict and Redis is skipped for a minute, so an
outage costs cache sharing between workers, not latency or availability.
"""

import json
import logging
import time
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger("cache")

_LOCAL_MAX = 5000
_REDIS_BACKOFF_SECONDS = 60

_redis: Optional[aioredis.Redis] = None
_redis_down_until = 0.0
_local: dict[str, tuple[float, Any]] = {}


def _get_redis() -> Optional[aioredis.Redis]:
    global _redis
    if time.monotonic() < _redis_down_until:
        return None
    if _redis is None:
        try:
            _redis = aioredis.from_url(
                settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1,
                decode_responses=True,
            )
        except Exception as e:
            logger.warning("Redis init failed: %s", type(e).__name__)
            return None
    return _redis


def _mark_redis_down() -> None:
    global _redis_down_until
    _redis_down_until = time.monotonic() + _REDIS_BACKOFF_SECONDS


async def cache_get(key: str) -> Optional[Any]:
    client = _get_redis()
    if client is not None:
        try:
            raw = await client.get(key)
            # Redis answered, so it is the source of truth: a miss means
            # "deleted or expired", and a stale process-local copy must not
            # resurrect it (that would defeat cache_delete across workers).
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning("Redis get failed: %s", type(e).__name__)
            _mark_redis_down()
    entry = _local.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    # Always keep a local copy so a Redis outage only costs cross-worker sharing.
    if len(_local) > _LOCAL_MAX:
        _local.clear()
    _local[key] = (time.monotonic() + ttl, value)

    client = _get_redis()
    if client is not None:
        try:
            await client.set(key, json.dumps(value), ex=ttl)
        except Exception as e:
            logger.warning("Redis set failed: %s", type(e).__name__)
            _mark_redis_down()


async def cache_delete(key: str) -> None:
    _local.pop(key, None)
    client = _get_redis()
    if client is not None:
        try:
            await client.delete(key)
        except Exception as e:
            logger.warning("Redis delete failed: %s", type(e).__name__)
            _mark_redis_down()
