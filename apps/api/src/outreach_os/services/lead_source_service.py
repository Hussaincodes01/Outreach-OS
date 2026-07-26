"""Per-tenant lead_source config service.

We auto-seed every known source (see `VALID_SOURCES`) on first read for a
tenant if none exist, so the UI can render a "check the boxes for what to
enable" view without the customer having to create rows manually.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.domain.models.lead_source import LeadSource, LeadSourceKind
from outreach_os.domain.schemas.lead_scraping import VALID_SOURCES


async def list_sources(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[LeadSource]:
    rows = (
        await session.execute(
            select(LeadSource)
            .where(LeadSource.tenant_id == tenant_id)
            .order_by(LeadSource.source.asc())
        )
    ).scalars().all()
    existing = {r.source for r in rows}
    missing = [s for s in VALID_SOURCES if s not in existing]
    if missing:
        for source in missing:
            session.add(LeadSource(tenant_id=tenant_id, source=source, is_enabled=False))
        await session.flush()
        rows = (
            await session.execute(
                select(LeadSource)
                .where(LeadSource.tenant_id == tenant_id)
                .order_by(LeadSource.source.asc())
            )
        ).scalars().all()
    return list(rows)


async def update_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source: str,
    is_enabled: bool | None,
    config: dict[str, Any] | None,
) -> LeadSource:
    if source not in VALID_SOURCES:
        from outreach_os.core.errors import ValidationError
        raise ValidationError(f"unknown source: {source}")
    row = (
        await session.execute(
            select(LeadSource).where(
                LeadSource.tenant_id == tenant_id, LeadSource.source == source
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = LeadSource(tenant_id=tenant_id, source=source, is_enabled=False, config={})
        session.add(row)
    if is_enabled is not None:
        row.is_enabled = is_enabled
    if config is not None:
        row.config = config
    await session.flush()
    return row


# Re-export the enum for convenience.
__all__ = ["LeadSourceKind", "list_sources", "update_source"]
