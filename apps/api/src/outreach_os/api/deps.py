"""FastAPI dependencies.

Outreach OS is a single-user tool: there is no authentication. Every request
acts as the one built-in local workspace (see `services.local_workspace`).
The data layer is still tenant-scoped, so RLS stays enforced underneath.

Two session flavours:
- `get_db` — bare session in a transaction. Use for health checks and for
  any flow that needs to set the RLS context itself.
- `get_scoped_db` — session with the local workspace's tenant bound to
  RLS. Use for every business endpoint.

`get_current_user` returns the local workspace's AuthContext
(user_id, tenant_id, role), creating the workspace rows on first use.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.schemas.auth import AuthContext
from outreach_os.services.local_workspace import ensure_local_workspace, local_auth_context


async def get_db() -> AsyncIterator[AsyncSession]:
    """Transaction-scoped session with NO RLS context.

    Use only for health checks or for code that sets the tenant context
    itself with `set_tenant_for_session`. Request handlers that read or
    write workspace data should depend on `get_scoped_db` instead.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        yield session


async def get_current_user() -> AuthContext:
    """The single local workspace. There is no authentication."""
    await ensure_local_workspace()
    return local_auth_context()


async def get_scoped_db(
    user: AuthContext = Depends(get_current_user),
) -> AsyncIterator[AsyncSession]:
    """Session bound to the current workspace's tenant via RLS.

    Use this in every business endpoint.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(user.tenant_id))
        yield session


__all__ = [
    "AuthContext",
    "get_current_user",
    "get_db",
    "get_scoped_db",
]
