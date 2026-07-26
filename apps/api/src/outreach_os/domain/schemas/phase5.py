"""Pydantic schemas for the Phase 5 meeting booking + CRM sync engine."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel, IdTimestampMixin

# --- Meeting ---

MEETING_STATUSES = (
    "proposed", "confirmed", "declined", "cancelled", "completed", "no_show",
)

# How many slot options we propose. Per the master plan, the scheduling
# agent offers 3 working-day slots.
PROPOSED_SLOT_COUNT = 3


class MeetingSlot(ApiModel):
    """One candidate slot in a meeting proposal.

    `index` 0-based position; `start` and `end` are the local times
    the user (lead) would see in their calendar. We always carry both
    so the ICS generator doesn't have to recompute end = start + duration.
    """
    index: int = Field(ge=0, le=PROPOSED_SLOT_COUNT - 1)
    start: datetime
    end: datetime


class MeetingCreateIn(ApiModel):
    """Manual meeting creation (rarely used \u2014 the agent auto-creates on
    positive reply). Useful for tests and ad-hoc book-by-hand cases."""
    lead_id: uuid.UUID
    mailbox_id: uuid.UUID | None = None
    subject: str = Field(min_length=1, max_length=200)
    agenda: str | None = None
    location: str | None = None
    duration_minutes: int = Field(default=30, ge=15, le=240)
    proposed_slots: list[MeetingSlot] = Field(min_length=1, max_length=PROPOSED_SLOT_COUNT)
    organizer_email: str
    attendee_email: str


class MeetingConfirmIn(ApiModel):
    """Pick one of the proposed_slots to confirm."""
    slot_index: int = Field(ge=0, le=PROPOSED_SLOT_COUNT - 1)


class MeetingOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    lead_id: uuid.UUID
    mailbox_id: uuid.UUID | None
    send_id: uuid.UUID | None
    reply_id: uuid.UUID | None
    subject: str
    agenda: str | None
    location: str | None
    duration_minutes: int
    proposed_slots: list[dict[str, Any]]
    chosen_slot: datetime | None
    status: str
    provider_event_id: str | None
    ics_uid: str
    ics_sequence: int
    organizer_email: str
    attendee_email: str
    proposed_at: datetime
    confirmed_at: datetime | None
    declined_at: datetime | None
    cancelled_at: datetime | None
    updated_at: datetime


class MeetingPage(ApiModel):
    items: list[MeetingOut]
    total: int
    limit: int
    offset: int


# --- CRM ---

CRM_PROVIDERS = ("google_sheets",)
CRM_CONNECTION_STATUSES = ("active", "paused", "error")


class CrmConnectionCreateIn(ApiModel):
    provider: str = Field(default="google_sheets")
    name: str = Field(min_length=1, max_length=100)
    spreadsheet_id: str | None = None
    sheet_range: str | None = "A:Z"
    column_mapping: dict[str, str] = Field(default_factory=dict)
    access_token_credential_id: uuid.UUID | None = None


class CrmConnectionUpdateIn(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    spreadsheet_id: str | None = None
    sheet_range: str | None = None
    column_mapping: dict[str, str] | None = None
    status: str | None = None


class CrmConnectionOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    provider: str
    name: str
    spreadsheet_id: str | None
    sheet_range: str | None
    column_mapping: dict[str, str]
    access_token_credential_id: uuid.UUID | None
    status: str
    last_sync_at: datetime | None
    last_sync_error: str | None
    updated_at: datetime


class CrmConnectionPage(ApiModel):
    items: list[CrmConnectionOut]
    total: int
    limit: int
    offset: int


class CrmSyncEventOut(IdTimestampMixin):
    tenant_id: uuid.UUID
    crm_connection_id: uuid.UUID
    meeting_id: uuid.UUID | None
    status: str
    row_written: dict[str, Any] | None
    error: str | None
    synced_at: datetime


class CrmSyncEventPage(ApiModel):
    items: list[CrmSyncEventOut]
    total: int
    limit: int
    offset: int
