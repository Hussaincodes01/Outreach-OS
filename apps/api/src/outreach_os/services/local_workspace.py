"""The single built-in workspace every request runs as.

Outreach OS runs as a single-user tool: there is no signup or login. The data
layer is still tenant-scoped (PostgreSQL RLS), so one fixed tenant and owner
user are created on first use and every request binds to them.
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import text

from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.schemas.auth import AuthContext

LOCAL_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
LOCAL_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
LOCAL_TENANT_SLUG = "local"
LOCAL_TENANT_NAME = "My Workspace"
LOCAL_USER_EMAIL = "owner@example.com"

_ensured = False
_lock = asyncio.Lock()


def local_auth_context() -> AuthContext:
    return AuthContext(user_id=LOCAL_USER_ID, tenant_id=LOCAL_TENANT_ID, role="owner")


def reset_local_workspace_cache() -> None:
    """Forget that the rows exist. Tests call this after truncating tables."""
    global _ensured
    _ensured = False


async def ensure_local_workspace() -> None:
    """Create the local tenant and owner user if missing. Safe to call repeatedly."""
    global _ensured
    if _ensured:
        return
    async with _lock:
        if _ensured:
            return
        factory = get_session_factory()
        async with factory() as session, session.begin():
            # tenant is not RLS-protected; app_user is, so bind the GUC first.
            await session.execute(
                text(
                    "INSERT INTO tenant (id, slug, name) VALUES (:id, :slug, :name) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": LOCAL_TENANT_ID, "slug": LOCAL_TENANT_SLUG, "name": LOCAL_TENANT_NAME},
            )
            await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
            # password_hash '!' is deliberately unusable: nothing verifies passwords.
            await session.execute(
                text(
                    "INSERT INTO app_user (id, tenant_id, email, password_hash, role) "
                    "VALUES (:id, :tid, :email, '!', 'owner') ON CONFLICT (id) DO NOTHING"
                ),
                {"id": LOCAL_USER_ID, "tid": LOCAL_TENANT_ID, "email": LOCAL_USER_EMAIL},
            )
        _ensured = True
