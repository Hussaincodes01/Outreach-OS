"""Tests for the lead dedup + insert path.

The DB has partial unique indexes on (tenant_id, email) and (tenant_id,
domain). The service layer also pre-filters to give a deterministic
"new vs duplicate" count. We exercise both layers.
"""
from __future__ import annotations

import uuid

import pytest

from outreach_os.services import lead_service
from outreach_os.services.scraping.raw_lead import RawLead

pytestmark = pytest.mark.asyncio


def _raw(*, email: str | None = None, domain: str | None = None, source: str = "company_site") -> RawLead:
    return RawLead(
        source=source,
        first_name="Alex",
        last_name="Doe",
        full_name="Alex Doe",
        email=email,
        domain=domain,
        company_name="Sample Co",
    )


async def test_dedup_within_single_call():
    """The service dedupes duplicates within a single insert_leads call."""
    from outreach_os.core.db import get_session_factory
    from outreach_os.core.tenancy import set_tenant_for_session

    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    async with factory() as session:
        async with session.begin():
            # Seed the tenant row (RLS doesn't apply, the tenant table is master).
            await session.execute(
                __import__("sqlalchemy").text(
                    "INSERT INTO tenant (id, name, slug) VALUES (:id, :n, :s)"
                ),
                {"id": str(tenant_id), "n": "test-dedup", "s": f"test-dedup-{tenant_id.hex[:6]}"},
            )
            await set_tenant_for_session(session, str(tenant_id))

            raw = [
                _raw(email="alex@example.com", domain="example.com"),
                _raw(email="alex@example.com", domain="example.com"),
                _raw(email="bob@example.com", domain="example.com"),
            ]
            inserted, duplicates = await lead_service.insert_leads(
                session, tenant_id=tenant_id, job_id=None, raw_leads=raw
            )
            assert inserted == 2
            assert duplicates == 1


async def test_dedup_against_existing_rows():
    """Leads already in the DB are skipped when a new batch comes in."""
    from outreach_os.core.db import get_session_factory
    from outreach_os.core.tenancy import set_tenant_for_session

    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    async with factory() as session:
        async with session.begin():
            await session.execute(
                __import__("sqlalchemy").text(
                    "INSERT INTO tenant (id, name, slug) VALUES (:id, :n, :s)"
                ),
                {"id": str(tenant_id), "n": "test-dedup2", "s": f"test-dedup2-{tenant_id.hex[:6]}"},
            )
            await set_tenant_for_session(session, str(tenant_id))

            # First call inserts one lead.
            inserted, _ = await lead_service.insert_leads(
                session,
                tenant_id=tenant_id,
                job_id=None,
                raw_leads=[_raw(email="a@x.com", domain="x.com")],
            )
            assert inserted == 1

            # Second call with the same lead must dedup.
            inserted, duplicates = await lead_service.insert_leads(
                session,
                tenant_id=tenant_id,
                job_id=None,
                raw_leads=[_raw(email="a@x.com", domain="x.com")],
            )
            assert inserted == 0
            assert duplicates == 1


async def test_db_unique_index_rejects_direct_duplicates():
    """The DB-level partial unique index is the safety net for races."""
    from sqlalchemy import text

    from outreach_os.core.db import get_session_factory
    from outreach_os.core.tenancy import set_tenant_for_session

    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("INSERT INTO tenant (id, name, slug) VALUES (:id, :n, :s)"),
                {"id": str(tenant_id), "n": "test-dedup3", "s": f"test-dedup3-{tenant_id.hex[:6]}"},
            )
            await set_tenant_for_session(session, str(tenant_id))
            await session.execute(
                text(
                    "INSERT INTO lead (tenant_id, source, email, domain) "
                    "VALUES (:t, 'company_site', 'a@y.com', 'y.com')"
                ),
                {"t": str(tenant_id)},
            )
        # New transaction — try to insert the same email again.
        with pytest.raises(Exception) as exc_info:
            async with session.begin():
                await set_tenant_for_session(session, str(tenant_id))
                await session.execute(
                    text(
                        "INSERT INTO lead (tenant_id, source, email, domain) "
                        "VALUES (:t, 'company_site', 'a@y.com', 'y.com')"
                    ),
                    {"t": str(tenant_id)},
                )
        # The unique-violation bubbles up as a Postgres IntegrityError;
        # we just want to confirm the constraint fires.
        assert "uq_lead_tenant_email" in str(exc_info.value) or "duplicate" in str(exc_info.value).lower()
