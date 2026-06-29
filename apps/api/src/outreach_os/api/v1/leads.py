"""Lead read + delete endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.domain.schemas.lead_scraping import LeadOut, LeadPage
from outreach_os.services import lead_service

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=LeadPage)
async def list_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> LeadPage:
    rows = await lead_service.list_leads(
        db,
        tenant_id=user.tenant_id,
        limit=limit,
        offset=offset,
        source=source,
    )
    total = await lead_service.count_leads(db, tenant_id=user.tenant_id)
    return LeadPage(
        items=[LeadOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    ok = await lead_service.delete_lead(
        db, tenant_id=user.tenant_id, lead_id=lead_id
    )
    if not ok:
        # 404 (not 403) so we don't reveal existence across tenants.
        raise HTTPException(status_code=404, detail="lead not found")
    await write_audit_event(
        db,
        action="lead.deleted",
        target_type="lead",
        target_id=lead_id,
        actor_kind="user",
        actor_id=user.user_id,
    )
