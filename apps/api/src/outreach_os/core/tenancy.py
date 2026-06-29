"""Multi-tenant context: sets the per-request RLS variable.

This is the linchpin of tenant isolation. Every API request that needs DB
access must call set_tenant_for_session at the start of its transaction.
The setting is transaction-scoped (`set_config(..., true)`) so it auto-
reverts at COMMIT/ROLLBACK — never use `false` (session-scope) or the GUC
will leak across requests that share a pooled connection.
"""
from __future__ import annotations

from contextvars import ContextVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

current_tenant_id: ContextVar[str | None] = ContextVar(
    "current_tenant_id", default=None
)


async def set_tenant_for_session(session: AsyncSession, tenant_id: str) -> None:
    """Bind the request's tenant to the session via Postgres' GUC.

    The third arg `true` makes the setting transaction-scoped, so it
    automatically reverts when the request transaction ends. ALWAYS use
    transaction-scope; using `false` (session-scope) leaks across requests
    that reuse a pooled connection.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required to set RLS context")
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tid, true)"),
        {"tid": tenant_id},
    )
    current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> str | None:
    return current_tenant_id.get()


def assert_tenant_set() -> str:
    """Raise if RLS context was not bound. Returns the tenant_id on success."""
    tid = current_tenant_id.get()
    if not tid:
        raise RuntimeError(
            "Tenant context not set. Did the request skip the auth dependency?"
        )
    return tid
