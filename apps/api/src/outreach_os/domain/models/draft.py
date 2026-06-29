"""Draft — the LLM-generated email body for a (campaign, lead, step).

A draft is created when a user clicks "Generate" on the campaigns page
(or when the Celery worker runs the LangGraph pipeline). The full body
is stored in S3 (`s3_key`) for audit, while a `body_preview` keeps a
short summary inline so the UI can render it without an S3 round-trip.

`status` flow:
    pending -> ready     (worker succeeded; user can review)
           \\-> failed  (worker errored; check `error`)
    ready   -> approved  (user clicked Approve)
           \\-> rejected (user clicked Reject; another draft will be generated)
    approved -> sent     (Phase 4 mailer fired)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class Draft(Base):
    __tablename__ = "draft"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        nullable=False,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("lead.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaign_step.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_draft_tenant", "tenant_id"),
        Index("ix_draft_campaign", "campaign_id"),
        Index("ix_draft_lead", "lead_id"),
        CheckConstraint(
            "status IN ('pending', 'ready', 'approved', 'rejected', 'sent', 'failed')",
            name="ck_draft_status",
        ),
    )
