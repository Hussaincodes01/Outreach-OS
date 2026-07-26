"""Phase 5 \u2014 Meetings API.

Authenticated CRUD over the `meeting` table. Lifecycle:
    proposed  \u2192  confirmed  \u2192  completed
       \u2193           \u2193
    declined   cancelled   no_show

Confirming a meeting creates the calendar event and auto-syncs the
meeting to any active CRM connections (via the reply-service hook on
positive replies; manual confirms do not auto-sync \u2014 call
POST /v1/crm/connections/{id}/sync for that).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.models.meeting import Meeting
from outreach_os.domain.schemas.phase5 import (
    MEETING_STATUSES,
    MeetingConfirmIn,
    MeetingOut,
    MeetingPage,
)
from outreach_os.services.crm_service import CrmService, CrmServiceError
from outreach_os.services.meeting_service import MeetingError, MeetingService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _to_out(m: Meeting) -> MeetingOut:
    return MeetingOut(
        id=m.id,
        created_at=m.created_at,
        tenant_id=m.tenant_id,
        lead_id=m.lead_id,
        mailbox_id=m.mailbox_id,
        send_id=m.send_id,
        reply_id=m.reply_id,
        subject=m.subject,
        agenda=m.agenda,
        location=m.location,
        duration_minutes=m.duration_minutes,
        proposed_slots=list(m.proposed_slots or []),
        chosen_slot=m.chosen_slot,
        status=m.status,
        provider_event_id=m.provider_event_id,
        ics_uid=m.ics_uid,
        ics_sequence=m.ics_sequence,
        organizer_email=m.organizer_email,
        attendee_email=m.attendee_email,
        proposed_at=m.proposed_at,
        confirmed_at=m.confirmed_at,
        declined_at=m.declined_at,
        cancelled_at=m.cancelled_at,
        updated_at=m.updated_at,
    )


@router.get("", response_model=MeetingPage)
async def list_meetings(
    status_: str | None = Query(default=None, alias="status"),
    lead_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> MeetingPage:
    if status_ is not None and status_ not in MEETING_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"invalid status: {status_!r}"
        )
    svc = MeetingService(db)
    items, total = await svc.list_meetings(
        tenant_id=user.tenant_id,
        status=status_,
        lead_id=lead_id,
        limit=limit, offset=offset,
    )
    return MeetingPage(
        items=[_to_out(m) for m in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{meeting_id}", response_model=MeetingOut)
async def get_meeting(
    meeting_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> MeetingOut:
    svc = MeetingService(db)
    meeting = await svc.get(tenant_id=user.tenant_id, meeting_id=meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    return _to_out(meeting)


@router.post(
    "/{meeting_id}/confirm",
    response_model=MeetingOut,
    status_code=status.HTTP_200_OK,
)
async def confirm_meeting(
    meeting_id: uuid.UUID,
    body: MeetingConfirmIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> MeetingOut:
    svc = MeetingService(db)
    try:
        meeting = await svc.confirm(
            tenant_id=user.tenant_id,
            meeting_id=meeting_id,
            slot_index=body.slot_index,
        )
    except MeetingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Best-effort: auto-sync to CRM on manual confirm. Failure is logged
    # but doesn't block the response \u2014 the user can re-sync via the
    # /v1/crm/connections/{id}/sync endpoint.
    try:
        crm_svc = CrmService(db)
        await crm_svc.sync_meeting(
            tenant_id=user.tenant_id, meeting_id=meeting.id
        )
    except CrmServiceError as exc:
        log.warning("crm sync after manual confirm failed: %s", exc)
    return _to_out(meeting)


@router.post(
    "/{meeting_id}/decline",
    response_model=MeetingOut,
    status_code=status.HTTP_200_OK,
)
async def decline_meeting(
    meeting_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> MeetingOut:
    svc = MeetingService(db)
    try:
        meeting = await svc.decline(
            tenant_id=user.tenant_id, meeting_id=meeting_id
        )
    except MeetingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(meeting)


@router.post(
    "/{meeting_id}/cancel",
    response_model=MeetingOut,
    status_code=status.HTTP_200_OK,
)
async def cancel_meeting(
    meeting_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> MeetingOut:
    svc = MeetingService(db)
    try:
        meeting = await svc.cancel(
            tenant_id=user.tenant_id, meeting_id=meeting_id
        )
    except MeetingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(meeting)


__all__ = ["router"]
