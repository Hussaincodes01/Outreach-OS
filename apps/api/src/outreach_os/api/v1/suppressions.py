"""Phase 4 — Suppression list (CAN-SPAM/GDPR blocklist)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.schemas.phase4 import (
    SuppressionCreateIn,
    SuppressionOut,
    SuppressionPage,
)
from outreach_os.services.suppression_service import SuppressionError, SuppressionService

router = APIRouter(prefix="/suppressions", tags=["suppressions"])


def _to_out(s) -> SuppressionOut:
    return SuppressionOut(
        id=s.id,
        created_at=s.created_at,
        tenant_id=s.tenant_id,
        email=s.email,
        reason=s.reason,
        source=s.source,
        notes=s.notes,
    )


@router.get("", response_model=SuppressionPage)
async def list_suppressions(
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SuppressionPage:
    svc = SuppressionService(db)
    items, total = await svc.list(tenant_id=user.tenant_id, limit=limit, offset=offset)
    return SuppressionPage(
        items=[_to_out(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=SuppressionOut, status_code=status.HTTP_201_CREATED)
async def add_suppression(
    data: SuppressionCreateIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SuppressionOut:
    svc = SuppressionService(db)
    try:
        row = await svc.add(tenant_id=user.tenant_id, data=data)
    except SuppressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.delete("/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_suppression(
    email: str,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    svc = SuppressionService(db)
    ok = await svc.remove(tenant_id=user.tenant_id, email=email)
    if not ok:
        raise HTTPException(status_code=404, detail="suppression not found")
