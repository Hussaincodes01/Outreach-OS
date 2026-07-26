"""CrmSyncEvent \u2014 append-only log of every CRM sync attempt.

Each row records one push of one meeting to one CRM connection. We keep
the full payload (row_written JSONB) for audit + replay. Failures are
recorded with the error message; the CrmConnection.last_sync_at /
last_sync_error columns mirror the most recent event for quick UI display.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base

if TYPE_CHECKING:
    from outreach_os.domain.models.meeting import Meeting



class CrmSyncEvent(Base):
    __tablename__ = "crm_sync_event"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    crm_connection_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("crm_connection.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("meeting.id", ondelete="CASCADE"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_written: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    meeting: Mapped[Meeting | None] = relationship("Meeting", back_populates="sync_events")

    __table_args__ = (
        Index("ix_crm_sync_event_tenant", "tenant_id"),
        Index("ix_crm_sync_event_meeting", "meeting_id"),
        Index("ix_crm_sync_event_status", "status"),
        CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_crm_sync_event_status",
        ),
    )
