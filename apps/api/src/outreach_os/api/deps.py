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

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.user import AppUser
from outreach_os.domain.schemas.auth import AuthContext
from outreach_os.services.local_workspace import ensure_local_workspace, local_auth_context


async def get_db() -> AsyncIterator[AsyncSession]:
    """Transaction-scoped session with NO RLS context.

    Use only for health checks or for flows that set the tenant context
    manually (e.g. the OAuth callback that resolves the tenant from a
    signed state token).
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


async def require_platform_admin(
    user: AuthContext = Depends(get_current_user),
) -> AuthContext:
    """Gate for the operator's own console.

    Checks the database rather than trusting a claim: revoking staff access
    must take effect immediately.

    The lookup runs on the caller's own tenant-scoped session, so this
    dependency cannot itself be used to read across tenants — it only answers
    "is the caller staff?".
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(user.tenant_id))
        row = await session.get(AppUser, user.user_id)
        is_admin = bool(row and row.is_platform_admin and row.is_active)
    if not is_admin:
        # 404, not 403: confirming the console exists tells a probing tenant
        # owner there is something worth attacking.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return user


async def get_admin_db() -> AsyncIterator[AsyncSession]:
    """Unscoped session for the admin console.

    No `app.current_tenant` is set, so RLS-protected tables return NOTHING
    here. That is deliberate: admin queries are restricted to the tables that
    genuinely hold no tenant-private content (tenant, plan), and anything
    needing per-tenant data binds that tenant explicitly. Weakening RLS to
    make an admin screen easier would defeat the product's main guarantee.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        yield session


__all__ = [
    "AuthContext",
    "get_admin_db",
    "get_current_user",
    "get_db",
    "get_scoped_db",
    "require_platform_admin",
]
