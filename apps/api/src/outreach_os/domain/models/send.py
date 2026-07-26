"""Send — a single email fired by a SequenceStep.

A Send is the persisted record of "we actually mailed this body to this
address at this time". One SequenceStep can have multiple Sends if the
user regenerates the draft — we keep history by linking through `step_id`.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base

if TYPE_CHECKING:
    from outreach_os.domain.models.reply import Reply
    from outreach_os.domain.models.sequence_step import SequenceStep
    from outreach_os.domain.models.tracking_event import TrackingEvent



class Send(Base):
    __tablename__ = "send"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sequence_step.id", ondelete="CASCADE"),
        nullable=False,
    )
    mailbox_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mailbox.id", ondelete="SET NULL"),
        nullable=True,
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("draft.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    from_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    message_id_header: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    clicked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    step: Mapped[SequenceStep] = relationship(
        "SequenceStep", back_populates="sends"
    )
    replies: Mapped[list[Reply]] = relationship(
        "Reply",
        back_populates="send",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tracking_events: Mapped[list[TrackingEvent]] = relationship(
        "TrackingEvent",
        back_populates="send",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_send_tenant", "tenant_id"),
        Index("ix_send_step", "step_id"),
        Index("ix_send_message_id", "message_id_header", unique=True),
        Index("ix_send_to_email", "tenant_id", "to_email"),
        Index("ix_send_status", "status"),
        CheckConstraint(
            "status IN ('queued', 'sent', 'bounced', 'failed', "
            "'unsubscribed', 'skipped')",
            name="ck_send_status",
        ),
    )
