"""Tenant creation logic. Centralised so the URL slug is consistent."""
from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.domain.models.tenant import Tenant

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def derive_slug(tenant_name: str) -> str:
    base = _SLUG_RE.sub("-", tenant_name.lower()).strip("-")
    return base[:50] or "tenant"


async def get_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    return await session.get(Tenant, tenant_id)


async def get_tenant_by_slug(session: AsyncSession, slug: str) -> Tenant | None:
    result = await session.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def create_tenant(
    session: AsyncSession,
    *,
    name: str,
    slug: str | None = None,
    plan: str = "free",
    tenant_id: uuid.UUID | None = None,
) -> Tenant:
    """Insert a new tenant row.

    The caller is responsible for setting the RLS context (`app.current_tenant`)
    to the new tenant's id BEFORE invoking this function, so that downstream
    writes in the same request (audit events, the first user) succeed under RLS.
    Pre-generate the tenant id (uuid4) and pass it via `tenant_id` so the caller
    can set the GUC first.
    """
    effective_slug = slug or derive_slug(name)
    existing = await get_tenant_by_slug(session, effective_slug)
    if existing is not None:
        # Avoid colliding slugs by appending a short suffix.
        suffix = uuid.uuid4().hex[:6]
        effective_slug = f"{effective_slug}-{suffix}"

    tenant = Tenant(id=tenant_id or uuid.uuid4(), name=name, slug=effective_slug, plan=plan)
    session.add(tenant)
    await session.flush()
    return tenant
