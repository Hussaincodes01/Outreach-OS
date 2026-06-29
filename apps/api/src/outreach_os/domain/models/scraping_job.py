"""A scrape job — async unit of work that runs an ICP against a list of sources.

The Celery task picks this up, iterates the sources, calls the scraping
service, dedupes into the `lead` table, and updates status + counts.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class ScrapingJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapingJob(Base):
    __tablename__ = "scraping_job"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    icp_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("icp.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=ScrapingJobStatus.PENDING.value
    )
    sources: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    found_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_scraping_job_tenant", "tenant_id"),
        Index("ix_scraping_job_status", "tenant_id", "status"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_scraping_job_status",
        ),
        CheckConstraint("requested_count >= 1", name="ck_scraping_job_requested_positive"),
    )
