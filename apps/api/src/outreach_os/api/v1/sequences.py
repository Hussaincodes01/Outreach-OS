"""Phase 4 — Sequence API: start / stop / list / get a SequenceRun."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.schemas.phase4 import (
    SequenceRunStartIn,
    SequenceRunOut,
)
from outreach_os.services.sequence_service import SequenceError, SequenceService

router = APIRouter(prefix="/sequences", tags=["sequences"])


def _to_out(
    run, stats: dict[str, int]
) -> SequenceRunOut:
    return SequenceRunOut(
        id=run.id,
        created_at=run.created_at,
        tenant_id=run.tenant_id,
        campaign_id=run.campaign_id,
        name=run.name,
        status=run.status,
        stopped_reason=run.stopped_reason,
        started_at=run.started_at,
        stopped_at=run.stopped_at,
        updated_at=run.updated_at,
        step_count=stats.get("step_count", 0),
        pending_count=stats.get("pending", 0),
        sent_count=stats.get("sent", 0),
        replied_count=stats.get("replied", 0),
        stopped_count=stats.get("stopped", 0),
    )


@router.post("", response_model=SequenceRunOut, status_code=status.HTTP_201_CREATED)
async def start_sequence(
    data: SequenceRunStartIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SequenceRunOut:
    svc = SequenceService(db)
    try:
        run = await svc.start_run(
            tenant_id=user.tenant_id,
            campaign_id=data.campaign_id,
            name=data.name,
            lead_ids=data.lead_ids,
            start_at=data.start_at,
            ignore_caps=data.ignore_caps,
        )
    except SequenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stats = await svc.run_stats(tenant_id=user.tenant_id, run_id=run.id)
    return _to_out(run, stats)


@router.get("", response_model=list[SequenceRunOut])
async def list_sequences(
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[SequenceRunOut]:
    svc = SequenceService(db)
    runs = await svc.list_runs(tenant_id=user.tenant_id, limit=limit, offset=offset)
    out: list[SequenceRunOut] = []
    for r in runs:
        stats = await svc.run_stats(tenant_id=user.tenant_id, run_id=r.id)
        out.append(_to_out(r, stats))
    return out


@router.get("/{run_id}", response_model=SequenceRunOut)
async def get_sequence(
    run_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SequenceRunOut:
    svc = SequenceService(db)
    result = await svc.get_run(tenant_id=user.tenant_id, run_id=run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="sequence run not found")
    run, _ = result
    stats = await svc.run_stats(tenant_id=user.tenant_id, run_id=run_id)
    return _to_out(run, stats)


@router.post("/{run_id}/stop", response_model=SequenceRunOut)
async def stop_sequence(
    run_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SequenceRunOut:
    svc = SequenceService(db)
    run = await svc.stop_run(tenant_id=user.tenant_id, run_id=run_id, reason="manual")
    if run is None:
        raise HTTPException(status_code=404, detail="sequence run not found")
    stats = await svc.run_stats(tenant_id=user.tenant_id, run_id=run_id)
    return _to_out(run, stats)
