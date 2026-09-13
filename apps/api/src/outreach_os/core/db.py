"""Async SQLAlchemy engine, session factory, and Declarative Base.

The session dependency (in api/deps.py) opens a transaction per request,
calls set_tenant_for_session to populate app.current_tenant for RLS,
yields the session, then commits/rolls back.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from outreach_os.core.config import get_settings

_T = TypeVar("_T")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Standalone session for scripts and workers."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_for_tests() -> None:
    """Test helper: clear cached engine/factory so settings changes apply."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def run_worker_task(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run `coro` on a fresh event loop and dispose the module-global async
    engine before that loop closes.

    Celery task wrappers (send_due, poll_inboxes, generate_draft,
    run_scraping_job, send_email_digest, ...) each call `asyncio.run(...)`
    per invocation. A prefork Celery worker handles MANY task invocations in
    the same OS process, so the `_engine` cached above by `get_engine()` —
    and the asyncpg connections / internal asyncio primitives its pool
    holds — survive from one `asyncio.run()` call to the next. But every
    `asyncio.run()` call opens a brand-new event loop, and SQLAlchemy's
    async engine binds its pool to whichever loop was running when it was
    first used. Reusing that cached engine from a second, different event
    loop raises "Task ... got Future ... attached to a different loop" the
    moment the pool tries to check out a connection — which is exactly what
    happens the second time any worker process handles an async-DB task
    (observed live: send_due / poll_inboxes both failed this way on their
    second run in the same forked worker).

    Disposing the engine here, inside the SAME loop that used it and right
    before that loop is torn down, forces the next call in this process to
    lazily rebuild a fresh engine bound to ITS OWN new loop. Cost: a new
    connection (pool) per task invocation — the right trade-off for
    beat-scheduled background tasks, which are not a request hot path.
    """

    async def _runner() -> _T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())
