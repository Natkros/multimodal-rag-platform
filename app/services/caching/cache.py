"""Phase 17: a thin Redis cache used for retrieval results. Opt-in
(`CACHE_ENABLED=true`, off by default — every prior "new capability" phase since
Phase 6 followed this same pattern) and a raw get/set wrapper rather than a generic
caching framework, since retrieval is currently the only thing worth caching here —
see docs/decisions/0017-phase17-caching.md for why, and what wasn't cached.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings


class CacheNotConfiguredError(RuntimeError):
    pass


@lru_cache
def _cached_redis_client(redis_url: str):
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


def get_redis_client(settings: Settings):
    if not settings.redis_url:
        raise CacheNotConfiguredError("CACHE_ENABLED=true requires REDIS_URL to be set.")
    return _cached_redis_client(settings.redis_url)


def cache_get(settings: Settings, key: str) -> str | None:
    return get_redis_client(settings).get(key)


def cache_set(settings: Settings, key: str, value: str) -> None:
    get_redis_client(settings).set(key, value, ex=settings.cache_ttl_seconds)
