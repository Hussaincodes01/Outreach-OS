"""FastAPI dependencies.

Two session flavours:
- `get_db` — bare session in a transaction. Use for login/signup/health
  and for any flow that needs to set the RLS context itself.
- `get_scoped_db` — session with the request's tenant already bound to
  RLS. Use for every authenticated business endpoint.

`get_current_user` decodes the bearer JWT and returns an AuthContext
(user_id, tenant_id, role). FastAPI caches sub-dependencies per request,
so calling `Depends(get_current_user)` multiple times in the same
endpoint stack only decodes the JWT once.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.auth import TokenError, decode_token
from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.schemas.auth import AuthContext


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()


async def get_db() -> AsyncIterator[AsyncSession]:
    """Transaction-scoped session with NO RLS context.

    Use only for endpoints that must run before a tenant exists
    (signup), for health checks, or for flows that set the tenant
    context manually (e.g. the OAuth callback that resolves the
    tenant from a signed state token).
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        yield session


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> AuthContext:
    """Decode JWT, return AuthContext. Does NOT open a DB session."""
    token = _bearer_token(authorization)
    try:
        payload = decode_token(token, expected_type="access")
    except (TokenError, JWTError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return AuthContext(
        user_id=uuid.UUID(str(payload["sub"])),
        tenant_id=uuid.UUID(str(payload["tid"])),
        role=str(payload.get("role", "member")),
    )


async def get_scoped_db(
    user: AuthContext = Depends(get_current_user),
) -> AsyncIterator[AsyncSession]:
    """Session bound to the authenticated user's tenant via RLS.

    Depends on get_current_user, so this only succeeds when the request
    is authenticated. Use this in every authenticated business endpoint.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(user.tenant_id))
        yield session


__all__ = ["AuthContext", "get_current_user", "get_db", "get_scoped_db"]
