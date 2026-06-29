"""Phase 3 — draft + agent-run endpoints.

The two write surfaces are:
- POST /v1/drafts/generate — kicks off the LangGraph pipeline
- PATCH /v1/drafts/{id} — user approves / rejects a draft (no email is sent
  in Phase 3; Phase 4 wires the mailer)

The read surfaces return drafts with a short inline `body_preview`; a
separate `?include_body=1` flag adds the full text + a presigned S3 URL.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.schemas.phase3 import (
    AgentRunOut,
    DraftOut,
    DraftPage,
    DraftUpdate,
    GenerateDraftIn,
)
from outreach_os.services.draft_service import (
    DraftError,
    DraftService,
)

router = APIRouter(prefix="/drafts", tags=["drafts"])


async def _resolve_step_campaign_id(
    db: AsyncSession, *, tenant_id: uuid.UUID, step_id: uuid.UUID
) -> uuid.UUID:
    """Resolve the campaign_id for a step within the current tenant.
    RLS-scoped, so cross-tenant step lookups return None."""
    result = await db.execute(
        select(CampaignStep.campaign_id).where(
            CampaignStep.tenant_id == tenant_id,
            CampaignStep.id == step_id,
        )
    )
    cid = result.scalar_one_or_none()
    if cid is None:
        raise DraftError(f"step {step_id} not found for this tenant")
    return cid


@router.get("", response_model=DraftPage)
async def list_drafts(
    campaign_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> DraftPage:
    svc = DraftService(db)
    try:
        items, total = await svc.list_drafts(
            tenant_id=user.tenant_id,
            campaign_id=campaign_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except DraftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DraftPage(items=items, total=total, limit=limit, offset=offset)


@router.post("/generate", response_model=DraftOut)
async def generate_draft(
    data: GenerateDraftIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> DraftOut:
    campaign_id = await _resolve_step_campaign_id(
        db, tenant_id=user.tenant_id, step_id=data.step_id
    )
    svc = DraftService(db)
    try:
        result = await svc.dispatch_generate_draft(
            tenant_id=user.tenant_id,
            campaign_id=campaign_id,
            lead_id=data.lead_id,
            step_id=data.step_id,
            force_regenerate=data.force_regenerate,
        )
    except DraftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    out = await svc.get_draft(tenant_id=user.tenant_id, draft_id=result.draft_id)
    if out is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="draft not found after generation",
        )
    return out


@router.get("/{draft_id}", response_model=DraftOut)
async def get_draft(
    draft_id: uuid.UUID,
    include_body: bool = Query(default=False),
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> DraftOut:
    svc = DraftService(db)
    out = await svc.get_draft(
        tenant_id=user.tenant_id, draft_id=draft_id, include_body=include_body
    )
    if out is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
    return out


@router.patch("/{draft_id}", response_model=DraftOut)
async def update_draft(
    draft_id: uuid.UUID,
    data: DraftUpdate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> DraftOut:
    svc = DraftService(db)
    try:
        out = await svc.update_draft(
            tenant_id=user.tenant_id,
            draft_id=draft_id,
            new_status=data.status,
            new_subject=data.subject,
            new_body_preview=data.body_preview,
        )
    except DraftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if out is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="draft not found")
    return out


# --- Agent runs (read-only) -----------------------------------------------


agent_router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


@agent_router.get("", response_model=list[AgentRunOut])
async def list_agent_runs(
    campaign_id: uuid.UUID | None = None,
    limit: int = 50,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[AgentRunOut]:
    svc = DraftService(db)
    runs = await svc.list_agent_runs(
        tenant_id=user.tenant_id, campaign_id=campaign_id, limit=limit
    )
    return [
        AgentRunOut(
            id=r.id,
            created_at=r.created_at,
            tenant_id=r.tenant_id,
            campaign_id=r.campaign_id,
            draft_id=r.draft_id,
            status=r.status,
            trace=r.trace,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            embeddings_tokens=r.embeddings_tokens,
            started_at=r.started_at,
            completed_at=r.completed_at,
            error=r.error,
        )
        for r in runs
    ]
