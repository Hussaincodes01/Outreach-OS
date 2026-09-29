"""User creation / lookup.

For cross-tenant user lookups (e.g. login by email), use the
`auth_user_by_email` SQL function, which is SECURITY DEFINER and so
bypasses RLS. In-tenant lookups can use `get_user_by_email` directly.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.auth import hash_password
from outreach_os.domain.models.user import AppUser, UserRole


async def get_user_by_email(
    session: AsyncSession, tenant_id: uuid.UUID, email: str
) -> AppUser | None:
    result = await session.execute(
        select(AppUser).where(
            AppUser.tenant_id == tenant_id, AppUser.email == email.lower()
        )
    )
    return result.scalar_one_or_none()


async def lookup_user_by_email(
    session: AsyncSession, email: str
) -> tuple[uuid.UUID, uuid.UUID, str, str] | None:
    """Cross-tenant user lookup used by the login flow.

    Uses the `auth_user_by_email` SQL function (SECURITY DEFINER) so it
    bypasses RLS. Returns (tenant_id, user_id, password_hash, role) or None.
    """
    row = (
        await session.execute(
            text(
                "SELECT tenant_id, user_id, password_hash, role "
                "FROM auth_user_by_email(:email)"
            ),
            {"email": email.lower()},
        )
    ).first()
    if row is None:
        return None
    return row[0], row[1], row[2], row[3]


async def create_user(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    email: str,
    password: str,
    role: UserRole = UserRole.MEMBER,
) -> AppUser:
    user = AppUser(
        tenant_id=tenant_id,
        email=email.lower(),
        password_hash=hash_password(password),
        role=role.value,
    )
    session.add(user)
    await session.flush()
    return user
