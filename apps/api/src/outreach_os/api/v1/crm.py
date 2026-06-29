"""Phase 5 \u2014 CRM connections API.

Authenticated CRUD for CrmConnection rows + per-meeting sync trigger.

Endpoints:
  GET    /v1/crm/connections            list
  POST   /v1/crm/connections            create
  GET    /v1/crm/connections/{id}       get
  PATCH  /v1/crm/connections/{id}       update
  DELETE /v1/crm/connections/{id}       delete
  POST   /v1/crm/connections/{id}/sync  sync one meeting to this connection
  GET    /v1/crm/sync-events            list all sync events for the tenant
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.schemas.phase5 import (
    CRM_CONNECTION_STATUSES,
    CrmConnectionCreateIn,
    CrmConnectionOut,
    CrmConnectionPage,
    CrmConnectionUpdateIn,
    CrmSyncEventOut,
    CrmSyncEventPage,
)
from outreach_os.services.crm_service import CrmService, CrmServiceError
from outreach_os.services.billing_service import BillingError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/crm", tags=["crm"])


def _conn_to_out(c) -> CrmConnectionOut:
    return CrmConnectionOut(
        id=c.id,
        created_at=c.created_at,
        tenant_id=c.tenant_id,
        provider=c.provider,
        name=c.name,
        spreadsheet_id=c.spreadsheet_id,
        sheet_range=c.sheet_range,
        column_mapping=dict(c.column_mapping or {}),
        access_token_credential_id=c.access_token_credential_id,
        status=c.status,
        last_sync_at=c.last_sync_at,
        last_sync_error=c.last_sync_error,
        updated_at=c.updated_at,
    )


def _sync_to_out(s) -> CrmSyncEventOut:
    return CrmSyncEventOut(
        id=s.id,
        created_at=s.synced_at,
        tenant_id=s.tenant_id,
        crm_connection_id=s.crm_connection_id,
        meeting_id=s.meeting_id,
        status=s.status,
        row_written=dict(s.row_written) if s.row_written else None,
        error=s.error,
        synced_at=s.synced_at,
    )


@router.get("/connections", response_model=CrmConnectionPage)
async def list_connections(
    status_: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CrmConnectionPage:
    if status_ is not None and status_ not in CRM_CONNECTION_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"invalid status: {status_!r}"
        )
    svc = CrmService(db)
    items, total = await svc.list_connections(
        tenant_id=user.tenant_id, status=status_,
        limit=limit, offset=offset,
    )
    return CrmConnectionPage(
        items=[_conn_to_out(c) for c in items],
        total=total, limit=limit, offset=offset,
    )


@router.post(
    "/connections",
    response_model=CrmConnectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    body: CrmConnectionCreateIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CrmConnectionOut:
    svc = CrmService(db)
    try:
        conn = await svc.create_connection(
            tenant_id=user.tenant_id,
            provider=body.provider,
            name=body.name,
            spreadsheet_id=body.spreadsheet_id,
            sheet_range=body.sheet_range,
            column_mapping=dict(body.column_mapping or {}),
            access_token_credential_id=body.access_token_credential_id,
        )
    except CrmServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _conn_to_out(conn)


@router.get("/connections/{connection_id}", response_model=CrmConnectionOut)
async def get_connection(
    connection_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CrmConnectionOut:
    svc = CrmService(db)
    conn = await svc.get_connection(
        tenant_id=user.tenant_id, connection_id=connection_id
    )
    if conn is None:
        raise HTTPException(status_code=404, detail="connection not found")
    return _conn_to_out(conn)


@router.patch("/connections/{connection_id}", response_model=CrmConnectionOut)
async def update_connection(
    connection_id: uuid.UUID,
    body: CrmConnectionUpdateIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CrmConnectionOut:
    svc = CrmService(db)
    try:
        conn = await svc.update_connection(
            tenant_id=user.tenant_id,
            connection_id=connection_id,
            name=body.name,
            spreadsheet_id=body.spreadsheet_id,
            sheet_range=body.sheet_range,
            column_mapping=body.column_mapping,
            status=body.status,
        )
    except CrmServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if conn is None:
        raise HTTPException(status_code=404, detail="connection not found")
    return _conn_to_out(conn)


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_connection(
    connection_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    svc = CrmService(db)
    deleted = await svc.delete_connection(
        tenant_id=user.tenant_id, connection_id=connection_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="connection not found")


@router.post(
    "/connections/{connection_id}/sync",
    response_model=CrmSyncEventPage,
    status_code=status.HTTP_200_OK,
)
async def sync_connection(
    connection_id: uuid.UUID,
    meeting_id: uuid.UUID = Query(...),
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CrmSyncEventPage:
    """Sync one meeting to one connection. Returns the resulting sync
    event so the UI can show success/failure + the row payload."""
    # Validate connection exists for tenant.
    crm_svc = CrmService(db)
    conn = await crm_svc.get_connection(
        tenant_id=user.tenant_id, connection_id=connection_id
    )
    if conn is None:
        raise HTTPException(status_code=404, detail="connection not found")
    # sync_meeting fans out to ALL active connections; for a manual
    # "sync THIS connection" call, we instead filter to just this one
    # by temporarily setting status filter via a custom code path:
    from outreach_os.domain.models.crm_connection import CrmConnection
    from sqlalchemy import select
    target = (await db.execute(
        select(CrmConnection).where(
            CrmConnection.id == connection_id,
            CrmConnection.tenant_id == user.tenant_id,
        )
    )).scalar_one()
    # Make the manual sync a no-op for active=paused connections.
    if target.status == "paused":
        raise HTTPException(
            status_code=400, detail="connection is paused; resume to sync"
        )
    # Single-conn sync: bypass sync_meeting and call _sync_one directly.
    from outreach_os.domain.models.meeting import Meeting
    from outreach_os.domain.models.lead import Lead
    meeting = (await db.execute(
        select(Meeting).where(
            Meeting.id == meeting_id, Meeting.tenant_id == user.tenant_id
        )
    )).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    lead = (await db.execute(
        select(Lead).where(
            Lead.id == meeting.lead_id, Lead.tenant_id == user.tenant_id
        )
    )).scalar_one_or_none()
    try:
        event = await crm_svc._sync_one(
            tenant_id=user.tenant_id, conn=target, meeting=meeting, lead=lead
        )
    except BillingError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    return CrmSyncEventPage(
        items=[_sync_to_out(event)], total=1, limit=1, offset=0,
    )


@router.get("/sync-events", response_model=CrmSyncEventPage)
async def list_sync_events(
    connection_id: uuid.UUID | None = None,
    meeting_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CrmSyncEventPage:
    svc = CrmService(db)
    items, total = await svc.list_sync_events(
        tenant_id=user.tenant_id,
        connection_id=connection_id,
        meeting_id=meeting_id,
        limit=limit, offset=offset,
    )
    return CrmSyncEventPage(
        items=[_sync_to_out(s) for s in items],
        total=total, limit=limit, offset=offset,
    )


__all__ = ["router"]
