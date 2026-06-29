"""Phase 4 — Sends API (read-only)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.schemas.phase4 import SEND_STATUSES, SendOut, SendPage
from outreach_os.services.send_service import SendService

router = APIRouter(prefix="/sends", tags=["sends"])


def _to_out(s) -> SendOut:
    return SendOut(
        id=s.id,
        created_at=s.created_at,
        tenant_id=s.tenant_id,
        step_id=s.step_id,
        mailbox_id=s.mailbox_id,
        draft_id=s.draft_id,
        to_email=s.to_email,
        from_email=s.from_email,
        subject=s.subject,
        body_text=s.body_text,
        message_id_header=s.message_id_header,
        provider_message_id=s.provider_message_id,
        status=s.status,
        error=s.error,
        queued_at=s.queued_at,
        sent_at=s.sent_at,
        opened_at=s.opened_at,
        clicked_at=s.clicked_at,
    )


@router.get("", response_model=SendPage)
async def list_sends(
    run_id: uuid.UUID | None = None,
    step_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SendPage:
    if status_filter is not None and status_filter not in SEND_STATUSES:
        raise HTTPException(status_code=400, detail=f"invalid status: {status_filter!r}")
    svc = SendService(db)
    items, total = await svc.list_sends(
        tenant_id=user.tenant_id,
        run_id=run_id,
        step_id=step_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SendPage(
        items=[_to_out(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{send_id}", response_model=SendOut)
async def get_send(
    send_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SendOut:
    svc = SendService(db)
    send = await svc.get_send(tenant_id=user.tenant_id, send_id=send_id)
    if send is None:
        raise HTTPException(status_code=404, detail="send not found")
    return _to_out(send)
