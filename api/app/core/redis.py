"""Redis connection pools.

Request handlers are sync (they run in FastAPI's threadpool next to sync SQLAlchemy),
so they use the sync client. The SSE stream and the QR rotator run on the event loop
and use the asyncio client. Both point at the same server.
"""
from __future__ import annotations

from typing import Optional

import redis
import redis.asyncio as aioredis

from app.core.config import settings

_sync_client: Optional[redis.Redis] = None
_async_client: Optional[aioredis.Redis] = None


def get_redis_client() -> redis.Redis:
    global _sync_client
    if _sync_client is None:
        _sync_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _sync_client


def get_async_redis_client() -> aioredis.Redis:
    global _async_client
    if _async_client is None:
        _async_client = aioredis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _async_client


def set_redis_clients(sync_client: redis.Redis, async_client: aioredis.Redis) -> None:
    """Swap the clients (used by tests to inject fakeredis)."""
    global _sync_client, _async_client
    _sync_client = sync_client
    _async_client = async_client


def get_redis() -> redis.Redis:
    """FastAPI dependency."""
    return get_redis_client()


def get_async_redis() -> aioredis.Redis:
    """FastAPI dependency for async endpoints."""
    return get_async_redis_client()


async def close_redis() -> None:
    global _sync_client, _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
    if _sync_client is not None:
        _sync_client.close()
        _sync_client = None
