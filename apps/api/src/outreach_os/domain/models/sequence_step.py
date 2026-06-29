"""SequenceStep — per-lead progress through a SequenceRun.

A row is created for each (lead, campaign_step) pair when a run starts.
`status` tracks the lifecycle: pending -> queued -> sent -> replied
| stopped | failed. `scheduled_at` is when the step becomes eligible
to send; the follow-up scheduler advances it.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class SequenceStep(Base):
    __tablename__ = "sequence_step"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sequence_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_step_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaign_step.id", ondelete="CASCADE"),
        nullable=False,
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("draft.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    scheduled_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_reply_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    run: Mapped["SequenceRun"] = relationship(  # noqa: F821
        "SequenceRun", back_populates="steps"
    )
    sends: Mapped[list["Send"]] = relationship(  # noqa: F821
        "Send",
        back_populates="step",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_sequence_step_tenant", "tenant_id"),
        Index("ix_sequence_step_run", "run_id"),
        Index("ix_sequence_step_scheduled", "scheduled_at"),
        Index("ix_sequence_step_status", "status"),
        UniqueConstraint(
            "run_id", "lead_id", "campaign_step_id",
            name="uq_sequence_step_run_lead_step",
        ),
        CheckConstraint(
            "status IN ('pending', 'queued', 'sent', 'replied', "
            "'stopped', 'failed', 'skipped')",
            name="ck_sequence_step_status",
        ),
    )
