#!/usr/bin/env python
"""Seed an admin tenant with admin/admin credentials."""
from __future__ import annotations

import asyncio
import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://outreach:outreach@localhost:5432/outreach")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.db import get_session_factory, dispose_engine
from outreach_os.core.auth import hash_password
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.models.user import AppUser, UserRole


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            # Check if admin tenant already exists
            existing = await session.execute(
                select(Tenant).where(Tenant.slug == "admin")
            )
            if existing.scalar_one_or_none():
                print("Admin tenant already exists")
                await dispose_engine()
                return

            # Create admin tenant
            tenant_id = uuid.uuid4()
            await set_tenant_for_session(session, str(tenant_id))

            tenant = Tenant(
                id=tenant_id,
                slug="admin",
                name="Admin Tenant",
                plan="scale",  # highest plan
                status="active",
            )
            session.add(tenant)

            # Create admin user
            user = AppUser(
                tenant_id=tenant_id,
                email="admin@admin.com",
                password_hash=hash_password("admin"),
                role=UserRole.OWNER,
                is_active=True,
            )
            session.add(user)

            await session.flush()
            print(f"Created admin tenant: {tenant.id}")
            print(f"Created admin user: {user.id} (email=admin, password=admin)")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
