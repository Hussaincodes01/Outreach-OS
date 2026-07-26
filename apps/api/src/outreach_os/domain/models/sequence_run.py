"""SequenceRun — a tenant's execution of a campaign over a lead cohort.

A `SequenceRun` is the runtime parent of a `Campaign`. It represents
"start running campaign X against these N leads". The campaign defines
the steps + style guide; the run tracks per-lead progress.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base

if TYPE_CHECKING:
    from outreach_os.domain.models.sequence_step import SequenceStep



class SequenceRun(Base):
    __tablename__ = "sequence_run"

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
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    stopped_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    steps: Mapped[list[SequenceStep]] = relationship(
        "SequenceStep",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_sequence_run_tenant", "tenant_id"),
        Index("ix_sequence_run_campaign", "campaign_id"),
        Index("uq_sequence_run_tenant_name", "tenant_id", "name", unique=True),
        CheckConstraint(
            "status IN ('running', 'paused', 'stopped', 'completed')",
            name="ck_sequence_run_status",
        ),
    )
