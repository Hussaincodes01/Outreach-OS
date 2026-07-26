"""Meeting \u2014 a proposed/confirmed/declined meeting with a lead.

Lifecycle:
    proposed  \u2192 confirmed  \u2192 completed
       \u2193           \u2193
    declined   cancelled
              \u2193
            no_show

When a positive reply comes in, ReplyService._classify_and_act calls
MeetingService.create_proposal() which generates 3 candidate slots. The
meeting is emailed to the lead (or surfaced in the UI for manual confirm).
On a counter-reply or manual POST /v1/meetings/{id}/confirm, status moves
to confirmed and a CalendarClient creates the actual calendar event
(provider_event_id stored here).

The `ics_uid` is globally unique and stable across status changes \u2014
iCalendar clients (Outlook, Apple Calendar) use it to recognise updates
to the same event across syncs.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base

if TYPE_CHECKING:
    from outreach_os.domain.models.crm_sync_event import CrmSyncEvent
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.mailbox import Mailbox



class Meeting(Base):
    __tablename__ = "meeting"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead.id", ondelete="CASCADE"),
        nullable=False,
    )
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mailbox.id", ondelete="SET NULL"),
        nullable=True,
    )
    send_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("send.id", ondelete="SET NULL"),
        nullable=True,
    )
    reply_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("reply.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    agenda: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    proposed_slots: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    chosen_slot: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="proposed")
    provider_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    ics_uid: Mapped[str] = mapped_column(Text, nullable=False)
    ics_sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    organizer_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    attendee_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    declined_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    lead: Mapped[Lead] = relationship("Lead")
    mailbox: Mapped[Mailbox | None] = relationship("Mailbox")
    sync_events: Mapped[list[CrmSyncEvent]] = relationship(
        "CrmSyncEvent",
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_meeting_tenant", "tenant_id"),
        Index("ix_meeting_lead", "lead_id"),
        Index("ix_meeting_status", "status"),
        Index("uq_meeting_ics_uid", "ics_uid", unique=True),
        CheckConstraint(
            "status IN ('proposed', 'confirmed', 'declined', 'cancelled', "
            "'completed', 'no_show')",
            name="ck_meeting_status",
        ),
    )
