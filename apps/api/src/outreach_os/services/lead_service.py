"""Lead service — dedup + persistence for scraped RawLead -> Lead rows.

Strategy: load the tenant's existing email + domain sets once, filter
in-memory, then bulk-insert. The DB-level partial unique indexes are
the safety net for concurrent inserts (race between two jobs running
at the same time).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.domain.models.lead import Lead
from outreach_os.services.scraping.raw_lead import RawLead


async def _existing_emails(session: AsyncSession, tenant_id: uuid.UUID) -> set[str]:
    """Return the set of existing emails for this tenant, lowercased."""
    result = await session.execute(
        select(Lead.email).where(Lead.tenant_id == tenant_id)
    )
    return {e.lower() for e in result.scalars().all() if e}


async def insert_leads(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID | None,
    raw_leads: Iterable[RawLead],
) -> tuple[int, int]:
    """Insert leads, deduping by email against the tenant's existing rows.

    Returns (inserted_count, duplicate_count). On a per-row unique
    violation (rare, race) we treat the row as a duplicate and
    continue.

    Note: we do NOT dedup on domain. Multiple contacts at the same
    company are legitimate (e.g. VP Sales + Head of Marketing both
    at Acme). The DB-level unique index on (tenant_id, email) is the
    race safety net.
    """
    raw_list = list(raw_leads)
    if not raw_list:
        return 0, 0

    existing_emails = await _existing_emails(session, tenant_id)
    new_emails: set[str] = set()
    rows: list[dict[str, Any]] = []

    for rl in raw_list:
        email_key = (rl.email or "").lower() or None

        if email_key and (email_key in existing_emails or email_key in new_emails):
            continue

        if email_key:
            new_emails.add(email_key)

        rows.append(
            {
                "tenant_id": tenant_id,
                "source": rl.source,
                "job_id": job_id,
                "first_name": rl.first_name,
                "last_name": rl.last_name,
                "full_name": rl.full_name,
                "email": rl.email.lower() if rl.email else None,
                "domain": rl.domain.lower() if rl.domain else None,
                "company_name": rl.company_name,
                "title": rl.title,
                "linkedin_url": rl.linkedin_url,
                "country": rl.country,
                "industry": rl.industry,
                "company_size": rl.company_size,
                "raw_data": rl.raw_data or {},
            }
        )

    if not rows:
        return 0, len(raw_list)

    duplicates = len(raw_list) - len(rows)
    # Per-row inserts wrapped in savepoints so a single unique-conflict
    # rolls back just that row, not the whole batch. The outer session
    # transaction stays usable after a conflict.
    inserted_count = 0
    for row in rows:
        try:
            async with session.begin_nested():
                await session.execute(pg_insert(Lead).values([row]))
            inserted_count += 1
        except IntegrityError:
            duplicates += 1
    await session.flush()
    return inserted_count, duplicates


async def list_leads(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    source: str | None = None,
) -> list[Lead]:
    stmt = (
        select(Lead)
        .where(Lead.tenant_id == tenant_id)
        .order_by(Lead.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if source:
        stmt = stmt.where(Lead.source == source)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_leads(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    from sqlalchemy import func

    result = await session.execute(
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id)
    )
    return int(result.scalar_one())


async def delete_lead(
    session: AsyncSession, *, tenant_id: uuid.UUID, lead_id: uuid.UUID
) -> bool:
    """Hard-delete a lead. Returns True if a row was removed.

    RLS guarantees the caller can only delete their own tenant's leads;
    a missing row returns False (which the endpoint maps to 404 — never
    403 — to avoid revealing cross-tenant existence).
    """
    lead = await session.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id:
        return False
    await session.delete(lead)
    await session.flush()
    return True
