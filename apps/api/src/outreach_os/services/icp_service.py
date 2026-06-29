"""ICP CRUD + scraping-job-launch logic.

The ICP service is the "what are we looking for" half. The scraping
service is the "how do we get them" half; this module stitches the
two together by creating a `scraping_job` row and dispatching the
Celery task that runs the actual scrape.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.errors import ConflictError, NotFoundError
from outreach_os.domain.models.icp import Icp
from outreach_os.domain.models.scraping_job import ScrapingJob, ScrapingJobStatus
from outreach_os.domain.schemas.lead_scraping import VALID_SOURCES


async def list_icps(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Icp]:
    result = await session.execute(
        select(Icp).where(Icp.tenant_id == tenant_id).order_by(Icp.created_at.desc())
    )
    return list(result.scalars().all())


async def get_icp(session: AsyncSession, *, tenant_id: uuid.UUID, icp_id: uuid.UUID) -> Icp:
    icp = await session.get(Icp, icp_id)
    if icp is None or icp.tenant_id != tenant_id:
        raise NotFoundError("icp not found")
    return icp


async def create_icp(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    description: str | None,
    industries: list[str],
    company_sizes: list[str],
    geos: list[str],
    titles: list[str],
    signals: list[str],
    extra: dict[str, Any],
    is_active: bool,
) -> Icp:
    icp = Icp(
        tenant_id=tenant_id,
        name=name,
        description=description,
        industries=industries,
        company_sizes=company_sizes,
        geos=geos,
        titles=titles,
        signals=signals,
        extra=extra,
        is_active=is_active,
    )
    session.add(icp)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"icp with name {name!r} already exists for this tenant") from exc
    return icp


async def update_icp(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    icp_id: uuid.UUID,
    fields: dict[str, Any],
) -> Icp:
    icp = await get_icp(session, tenant_id=tenant_id, icp_id=icp_id)
    for key, value in fields.items():
        if value is None and key not in {"is_active"}:
            continue
        setattr(icp, key, value)
    icp.updated_at = datetime.utcnow()
    await session.flush()
    return icp


async def delete_icp(session: AsyncSession, *, tenant_id: uuid.UUID, icp_id: uuid.UUID) -> None:
    icp = await get_icp(session, tenant_id=tenant_id, icp_id=icp_id)
    await session.delete(icp)
    await session.flush()


# --- Job launch ---

async def create_scraping_job(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    icp_id: uuid.UUID,
    sources: list[str],
    requested_count: int,
) -> ScrapingJob:
    # Validate ICP belongs to tenant.
    await get_icp(session, tenant_id=tenant_id, icp_id=icp_id)
    # Validate sources.
    unknown = [s for s in sources if s not in VALID_SOURCES]
    if unknown:
        from outreach_os.core.errors import ValidationError
        raise ValidationError(f"unknown sources: {unknown}")
    if not sources:
        sources = list(VALID_SOURCES)
    job = ScrapingJob(
        tenant_id=tenant_id,
        icp_id=icp_id,
        sources=sources,
        requested_count=requested_count,
        status=ScrapingJobStatus.PENDING.value,
    )
    session.add(job)
    await session.flush()
    return job


async def dispatch_scrape_job(job_id: uuid.UUID, tenant_id: uuid.UUID) -> dict | None:
    """Run the scrape job, in-process in tests, queued to Celery in prod.

    In production we return None immediately and a Celery worker picks
    up the task from the broker. In tests (eager mode) we `await` the
    async core directly so the same event loop drives both the HTTP
    request and the worker logic. The latter keeps the SQLAlchemy
    async engine bound to a single loop (no `asyncio.run` nesting).
    """
    from outreach_os.core.config import get_settings

    settings = get_settings()
    if settings.celery_task_always_eager:
        from outreach_os.workers.tasks.scrape import run_scraping_job_async
        return await run_scraping_job_async(job_id, tenant_id)
    from outreach_os.workers.tasks.scrape import run_scraping_job
    run_scraping_job.delay(str(job_id), str(tenant_id))
    return None
