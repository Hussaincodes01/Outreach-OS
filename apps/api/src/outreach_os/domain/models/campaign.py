"""Campaign — a tenant's outreach push.

A campaign owns:
- a style guide (3 sample emails the customer wrote + free-form notes)
- a sequence of `CampaignStep`s (1..N)
- generated `Draft` rows (one per (lead, step) pair)
- `AgentRun` rows that record each LangGraph invocation

The campaign's `llm_model` overrides the global `LLM_DEFAULT_MODEL` if set,
so a tenant can route specific campaigns to a different provider/model.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import Boolean, TIMESTAMP

from outreach_os.core.db import Base


class Campaign(Base):
    __tablename__ = "campaign"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    # LiteLLM model name, e.g. "openai/gpt-4o-mini". None -> use the default.
    llm_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Style guide: up to 3 sample emails the customer wrote.
    style_sample_emails: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    style_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    # Use a string forward reference to break the import cycle (campaign_step
    # imports this class for its FK). Use cascade="all, delete-orphan" so
    # removing a step from `campaign.steps` deletes the row.
    steps: Mapped[list["CampaignStep"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "CampaignStep",
        back_populates="campaign",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_campaign_tenant", "tenant_id"),
        Index("uq_campaign_tenant_name", "tenant_id", "name", unique=True),
        CheckConstraint("char_length(name) > 0", name="ck_campaign_name_nonempty"),
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name="ck_campaign_status",
        ),
    )
