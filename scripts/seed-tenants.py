"""Seed two demo tenants for manual exploration.

Run after `alembic upgrade head`:

    python scripts/seed-tenants.py

It prints the credentials at the end. Safe to re-run — it skips tenants
that already exist with the given slug.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make the API package importable when this script is run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api" / "src"))

from sqlalchemy import select  # noqa: E402

from outreach_os.core.auth import hash_password  # noqa: E402
from outreach_os.core.db import session_scope  # noqa: E402
from outreach_os.core.tenancy import set_tenant_for_session  # noqa: E402
from outreach_os.domain.models.tenant import Tenant  # noqa: E402
from outreach_os.domain.models.user import AppUser, UserRole  # noqa: E402


SEEDS = [
    {
        "tenant": {"name": "Acme (demo)", "slug": "acme-demo"},
        "user": {"email": "owner@acme-demo.example.com", "password": "correct-horse-battery-staple"},
    },
    {
        "tenant": {"name": "Globex (demo)", "slug": "globex-demo"},
        "user": {"email": "owner@globex-demo.example.com", "password": "correct-horse-battery-staple"},
    },
]


async def seed_one(payload: dict) -> tuple[str, str] | None:
    async with session_scope() as session:
        existing = await session.execute(
            select(Tenant).where(Tenant.slug == payload["tenant"]["slug"])
        )
        if existing.scalar_one_or_none() is not None:
            print(f"  skip: {payload['tenant']['slug']} already exists")
            return None

        tenant = Tenant(
            name=payload["tenant"]["name"],
            slug=payload["tenant"]["slug"],
            plan="free",
        )
        session.add(tenant)
        await session.flush()

        await set_tenant_for_session(session, str(tenant.id))

        user = AppUser(
            tenant_id=tenant.id,
            email=payload["user"]["email"],
            password_hash=hash_password(payload["user"]["password"]),
            role=UserRole.OWNER.value,
        )
        session.add(user)
        await session.flush()

        return tenant.slug, user.email


async def main() -> None:
    print("Seeding demo tenants…")
    for payload in SEEDS:
        result = await seed_one(payload)
        if result:
            slug, email = result
            print(f"  created: {slug} / {email}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
