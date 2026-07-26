"""Tenant model \u2014 master table, NOT under RLS.

Access to the tenant table is gated by the application layer: an
authenticated owner/admin user can only read their own tenant row by id.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    # Phase 7: monthly rollup counters (cheap to read on the dashboard).
    # Real-time deltas live in usage_event; this is the rollup.
    month_usage_sends: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    month_usage_leads: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    month_usage_llm_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    month_usage_reset_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False,
        server_default=text("date_trunc('month', now())"),
    )
    # BYOK: the model this tenant drafts with, as a LiteLLM `provider/model`
    # string. NULL means "use the server default". The provider prefix decides
    # which of the tenant's own API keys gets used.
    default_llm_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Embedding model for the knowledge base. Separate from the chat model
    # because most providers have no embeddings API — an Anthropic-only
    # workspace still needs somewhere to send embedding calls.
    embedding_llm_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Self-serve onboarding progress, e.g. {"llm_connected": true, ...}.
    # Free-form so adding a step doesn't need a migration.
    onboarding_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'cancelled')", name="ck_tenant_status"),
        CheckConstraint("plan IN ('free', 'starter', 'growth', 'scale', 'enterprise')",
                        name="ck_tenant_plan"),
    )
