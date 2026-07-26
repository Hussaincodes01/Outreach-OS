"""Lazy Redis client.

We avoid creating the connection at import time so tests that don't use
Redis (and the conftest that sets CELERY_TASK_ALWAYS_EAGER) don't pay
the cost. The first `get_redis()` call opens a single sync Redis client
and reuses it for the life of the process.
"""
from __future__ import annotations

import contextlib
from threading import Lock

import redis

from outreach_os.core.config import get_settings

_lock = Lock()
_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            settings = get_settings()
            _client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
    return _client


def reset_for_tests() -> None:
    global _client
    with _lock:
        if _client is not None:
            # Best-effort close: the pool is being discarded either way.
            with contextlib.suppress(Exception):
                _client.close()
            _client = None
