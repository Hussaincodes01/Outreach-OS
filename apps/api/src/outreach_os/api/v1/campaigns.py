"""Phase 3 — campaign CRUD + step management endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.schemas.phase3 import (
    CampaignCreate,
    CampaignOut,
    CampaignStepIn,
    CampaignStepOut,
    CampaignUpdate,
)
from outreach_os.services.campaign_service import CampaignError, CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _to_step_out(s) -> CampaignStepOut:
    return CampaignStepOut(
        id=s.id,
        created_at=s.created_at,
        tenant_id=s.tenant_id,
        campaign_id=s.campaign_id,
        step_number=s.step_number,
        delay_days=s.delay_days,
        subject_template=s.subject_template,
        goal=s.goal,
    )


def _to_campaign_out(c, steps) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        created_at=c.created_at,
        updated_at=c.updated_at,
        tenant_id=c.tenant_id,
        name=c.name,
        description=c.description,
        status=c.status,
        llm_model=c.llm_model,
        style_sample_emails=list(c.style_sample_emails or []),
        style_notes=c.style_notes,
        is_active=c.is_active,
        steps=[_to_step_out(s) for s in steps],
    )


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[CampaignOut]:
    svc = CampaignService(db)
    rows = await svc.list_campaigns(tenant_id=user.tenant_id)
    return [_to_campaign_out(c, steps) for c, steps in rows]


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    data: CampaignCreate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CampaignOut:
    svc = CampaignService(db)
    try:
        c, steps = await svc.create_campaign(tenant_id=user.tenant_id, data=data)
    except CampaignError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_campaign_out(c, steps)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CampaignOut:
    svc = CampaignService(db)
    result = await svc.get_campaign(tenant_id=user.tenant_id, campaign_id=campaign_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign not found")
    c, steps = result
    return _to_campaign_out(c, steps)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID,
    data: CampaignUpdate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CampaignOut:
    svc = CampaignService(db)
    try:
        result = await svc.update_campaign(
            tenant_id=user.tenant_id, campaign_id=campaign_id, data=data
        )
    except CampaignError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign not found")
    c, steps = result
    return _to_campaign_out(c, steps)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    svc = CampaignService(db)
    ok = await svc.delete_campaign(tenant_id=user.tenant_id, campaign_id=campaign_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign not found")


@router.put(
    "/{campaign_id}/steps", response_model=list[CampaignStepOut]
)
async def replace_steps(
    campaign_id: uuid.UUID,
    steps: list[CampaignStepIn],
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[CampaignStepOut]:
    """Atomically replace the campaign's steps."""
    svc = CampaignService(db)
    try:
        new_steps = await svc.replace_steps(
            tenant_id=user.tenant_id, campaign_id=campaign_id, steps=steps
        )
    except CampaignError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if new_steps is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign not found")
    return [_to_step_out(s) for s in new_steps]
