"""TrackingEvent — open/click hit recorded by the tracking endpoints.

A single event is appended per pixel-load or per link-click. `send_id`
denormalizes the parent; the `event_type` column is constrained to
('open', 'click') at the DB level.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base

if TYPE_CHECKING:
    from outreach_os.domain.models.send import Send



class TrackingEvent(Base):
    __tablename__ = "tracking_event"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    send_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("send.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET(), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    send: Mapped[Send] = relationship(
        "Send", back_populates="tracking_events"
    )

    __table_args__ = (
        Index("ix_tracking_event_tenant", "tenant_id"),
        Index("ix_tracking_event_send", "send_id"),
        Index("ix_tracking_event_type", "event_type"),
        CheckConstraint(
            "event_type IN ('open', 'click')", name="ck_tracking_event_type"
        ),
    )
