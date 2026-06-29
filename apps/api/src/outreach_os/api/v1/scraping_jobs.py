"""Scraping job read endpoints (creation lives under /icps/{id}/scrape)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.models.scraping_job import ScrapingJob
from outreach_os.domain.schemas.lead_scraping import ScrapingJobOut

router = APIRouter(prefix="/scraping-jobs", tags=["scraping-jobs"])


@router.get("", response_model=list[ScrapingJobOut])
async def list_jobs(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[ScrapingJobOut]:
    result = await db.execute(
        select(ScrapingJob)
        .where(ScrapingJob.tenant_id == user.tenant_id)
        .order_by(ScrapingJob.created_at.desc())
        .limit(100)
    )
    return [ScrapingJobOut.model_validate(r) for r in result.scalars().all()]


@router.get("/{job_id}", response_model=ScrapingJobOut)
async def get_job(
    job_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> ScrapingJobOut:
    job = await db.get(ScrapingJob, job_id)
    if job is None or job.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="scraping job not found")
    return ScrapingJobOut.model_validate(job)
