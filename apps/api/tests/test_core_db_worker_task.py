"""Regression test for `core.db.run_worker_task`.

Bug (found live, running the real docker compose stack for Task 9): a
Celery prefork worker process handles MANY task invocations over its
lifetime, but each task wrapper (`send_due`, `poll_inboxes`,
`generate_draft`, `run_scraping_job`, `send_email_digest`) calls
`asyncio.run(...)` once per invocation -- and `asyncio.run` opens a
brand-new event loop every single time. `core.db.get_engine()` /
`get_session_factory()` cache a SINGLE `AsyncEngine` at module scope for
the life of the process. SQLAlchemy's async engine binds its connection
pool's internal asyncio primitives to whichever event loop was running the
first time the engine was used. So the moment a SECOND task in the same
worker process tries to use that cached engine -- now from a second,
different event loop -- checking out a connection raises:

    RuntimeError: Task <Task pending name='Task-7' ...> got Future
    <Future pending ...> attached to a different loop

This was observed for real: `beat` fired `send_due` then, ~60s later,
`poll_inboxes` and `send_due` again; whichever forked worker child handled
its SECOND async-DB task crashed with exactly this error (see
task-9-report.md for the live log excerpt).

`run_worker_task` fixes it by disposing the module-global engine at the end
of the SAME loop that used it, right before that loop closes -- forcing the
next call in the process to lazily rebuild a fresh engine bound to its own
new loop.

The test below runs on a spawned thread (not directly in the test body) so
the result is independent of whatever event loop pytest-asyncio's own
autouse fixtures may be managing on the main thread -- exactly the "run it
in a thread with its own loop" pattern `workers/tasks/scrape.py` already
uses for the same reason. The module-global engine cache in `core.db` is
process-wide (not thread-local), so two sequential calls on that one
thread reproduce what two sequential task invocations in the same forked
Celery worker process do.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import text

from outreach_os.core.db import reset_for_tests, run_worker_task, session_scope

_T = TypeVar("_T")


async def _touch_db() -> int:
    async with session_scope() as session:
        result = await session.execute(text("SELECT 1"))
        return result.scalar_one()


def _run_in_thread(fn: Callable[[], _T]) -> _T:
    """Run `fn` on a fresh thread and propagate its return value/exception
    back to the caller. Isolates the asyncio.run() calls inside `fn` from
    any event loop the main test thread (pytest-asyncio) is managing."""
    box: dict[str, object] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised on the caller's thread
            box["error"] = exc

    t = threading.Thread(target=_target)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


def test_run_worker_task_survives_repeated_invocations_in_one_process() -> None:
    """Two back-to-back `run_worker_task` calls on the same
    thread -- simulating two Celery task invocations handled by the same
    forked worker process -- both succeed, because each call disposes the
    engine before its own loop closes."""
    reset_for_tests()

    def _twice_with_fix() -> tuple[int, int]:
        first = run_worker_task(_touch_db())
        second = run_worker_task(_touch_db())
        return first, second

    try:
        assert _run_in_thread(_twice_with_fix) == (1, 1)
    finally:
        reset_for_tests()
