"""ICP CRUD + scraping-job launch endpoints."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.errors import NotFoundError
from outreach_os.domain.schemas.lead_scraping import (
    IcpCreate,
    IcpOut,
    IcpUpdate,
    ScrapingJobCreate,
    ScrapingJobOut,
)
from outreach_os.services import icp_service

router = APIRouter(prefix="/icps", tags=["icps"])


@router.get("", response_model=list[IcpOut])
async def list_icps(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[IcpOut]:
    rows = await icp_service.list_icps(db, tenant_id=user.tenant_id)
    return [IcpOut.model_validate(r) for r in rows]


@router.post("", response_model=IcpOut, status_code=status.HTTP_201_CREATED)
async def create_icp(
    payload: IcpCreate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> IcpOut:
    icp = await icp_service.create_icp(
        db,
        tenant_id=user.tenant_id,
        name=payload.name,
        description=payload.description,
        industries=payload.industries,
        company_sizes=payload.company_sizes,
        geos=payload.geos,
        titles=payload.titles,
        signals=payload.signals,
        extra=payload.extra,
        is_active=payload.is_active,
    )
    await write_audit_event(
        db,
        action="icp.created",
        target_type="icp",
        target_id=icp.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"name": icp.name},
    )
    return IcpOut.model_validate(icp)


@router.get("/{icp_id}", response_model=IcpOut)
async def get_icp(
    icp_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> IcpOut:
    icp = await icp_service.get_icp(db, tenant_id=user.tenant_id, icp_id=icp_id)
    return IcpOut.model_validate(icp)


@router.patch("/{icp_id}", response_model=IcpOut)
async def update_icp(
    icp_id: uuid.UUID,
    payload: IcpUpdate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> IcpOut:
    fields: dict[str, Any] = payload.model_dump(exclude_unset=True)
    icp = await icp_service.update_icp(
        db, tenant_id=user.tenant_id, icp_id=icp_id, fields=fields
    )
    await write_audit_event(
        db,
        action="icp.updated",
        target_type="icp",
        target_id=icp.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"fields": list(fields.keys())},
    )
    return IcpOut.model_validate(icp)


@router.delete("/{icp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_icp(
    icp_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    try:
        await icp_service.delete_icp(db, tenant_id=user.tenant_id, icp_id=icp_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await write_audit_event(
        db,
        action="icp.deleted",
        target_type="icp",
        target_id=icp_id,
        actor_kind="user",
        actor_id=user.user_id,
    )


@router.post(
    "/{icp_id}/scrape",
    response_model=ScrapingJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def launch_scrape(
    icp_id: uuid.UUID,
    payload: ScrapingJobCreate | None = None,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> ScrapingJobOut:
    """Create a scraping_job and dispatch the Celery task.

    The dispatch happens via `BackgroundTasks` AFTER the request
    transaction commits — this guarantees the worker can find the
    job row when it picks the task up. Returns 202 with the freshly
    created job (status=pending). The UI polls `/scraping-jobs/{id}`
    for status.
    """
    payload = payload or ScrapingJobCreate(icp_id=icp_id)
    if payload.icp_id != icp_id:
        raise HTTPException(status_code=400, detail="icp_id mismatch between body and path")
    job = await icp_service.create_scraping_job(
        db,
        tenant_id=user.tenant_id,
        icp_id=icp_id,
        sources=payload.sources,
        requested_count=payload.requested_count,
    )
    await write_audit_event(
        db,
        action="scraping_job.created",
        target_type="scraping_job",
        target_id=job.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"sources": job.sources, "requested_count": job.requested_count},
    )
    # Commit before dispatching: the Celery task (in eager mode) opens
    # a NEW session to read the job, and it must see the committed row.
    # In production with .delay() this commit lands first regardless,
    # but the explicit commit keeps the test-mode behaviour correct.
    await db.commit()
    await icp_service.dispatch_scrape_job(job.id, user.tenant_id)
    return ScrapingJobOut.model_validate(job)
