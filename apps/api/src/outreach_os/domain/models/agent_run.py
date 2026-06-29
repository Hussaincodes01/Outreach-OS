"""AgentRun — a single LangGraph invocation record.

Each time the worker runs the campaign agent for a (campaign, lead, step),
one row is written. The `trace` JSONB captures per-node inputs/outputs
for debugging. Token counters are kept so a customer can see real LLM cost.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class AgentRun(Base):
    __tablename__ = "agent_run"

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
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("draft.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    trace: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    embeddings_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_agent_run_tenant", "tenant_id"),
        Index("ix_agent_run_campaign", "campaign_id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_agent_run_status",
        ),
    )
