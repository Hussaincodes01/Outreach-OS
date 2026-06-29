"""Per-tenant lead source configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.errors import ValidationError
from outreach_os.domain.schemas.lead_scraping import LeadSourceOut, LeadSourceUpdate
from outreach_os.services import lead_source_service

router = APIRouter(prefix="/lead-sources", tags=["lead-sources"])


@router.get("", response_model=list[LeadSourceOut])
async def list_sources(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[LeadSourceOut]:
    rows = await lead_source_service.list_sources(db, tenant_id=user.tenant_id)
    return [LeadSourceOut.model_validate(r) for r in rows]


@router.patch("/{source}", response_model=LeadSourceOut)
async def update_source(
    source: str,
    payload: LeadSourceUpdate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> LeadSourceOut:
    try:
        row = await lead_source_service.update_source(
            db,
            tenant_id=user.tenant_id,
            source=source,
            is_enabled=payload.is_enabled,
            config=payload.config,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await write_audit_event(
        db,
        action="lead_source.updated",
        target_type="lead_source",
        target_id=row.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"source": row.source, "is_enabled": row.is_enabled},
    )
    return LeadSourceOut.model_validate(row)
