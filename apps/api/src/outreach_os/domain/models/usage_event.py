"""Per-tenant metered usage event.

Append-only. Written by the same services that perform the work
(send, scraping, agent). The Tenant.month_usage_* counters are
periodic rollups of these rows (cheaper to read on the dashboard).

The rollup job lives in `workers/tasks/billing.py` and runs hourly.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from outreach_os.core.db import Base


class UsageEvent(Base):
    __tablename__ = "usage_event"
    __table_args__ = (
        CheckConstraint(
            "metric IN ('send','lead_scraped','llm_token_in','llm_token_out')",
            name="ck_usage_event_metric",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


Index("ix_usage_event_tenant_metric", UsageEvent.tenant_id, UsageEvent.metric)


__all__ = ["UsageEvent"]
