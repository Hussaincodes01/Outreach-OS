"""Ideal Customer Profile (ICP) — the targeting spec a customer defines.

A tenant has zero or more ICPs. When a scrape job runs, it references one
ICP and a list of enabled `lead_source` rows. The ICP fields are advisory
filters the scraping service applies to source results.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP, Boolean

from outreach_os.core.db import Base


class Icp(Base):
    __tablename__ = "icp"

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

    # All advisory filters. Empty list = no constraint on that field.
    industries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    company_sizes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    geos: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    titles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    signals: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")

    # Free-form extra fields the scraper may use (e.g. excluded_domains).
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_icp_tenant", "tenant_id"),
        Index("uq_icp_tenant_name", "tenant_id", "name", unique=True),
        CheckConstraint("char_length(name) > 0", name="ck_icp_name_nonempty"),
    )
