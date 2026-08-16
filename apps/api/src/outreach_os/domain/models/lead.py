"""A scraped lead — the output of running an ICP against a lead source.

Dedup is enforced at the DB level per tenant: a tenant cannot have two
leads with the same (email) or (domain) (only when those fields are set).
Source-specific raw payload lives in `raw_data` for audit / re-scoring.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class Lead(Base):
    __tablename__ = "lead"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scraping_job.id", ondelete="SET NULL"),
        nullable=True,
    )

    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_size: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_lead_tenant", "tenant_id"),
        Index("ix_lead_tenant_source", "tenant_id", "source"),
        Index("ix_lead_tenant_job", "tenant_id", "job_id"),
        # Dedup: same email twice in one tenant is a violation. NULL emails
        # are allowed (multiple uncontactable rows are fine). We do NOT
        # dedup on (tenant_id, domain) — multiple contacts at the same
        # company (e.g. VP Sales + Head of Marketing both at Acme) are
        # legitimate.
        Index(
            "uq_lead_tenant_email",
            "tenant_id",
            "email",
            unique=True,
            # `text(...)`, not the `Text` column type — the latter silently
            # builds a type with length="email IS NOT NULL" instead of an
            # index predicate (cf. notification.py / subscription.py).
            postgresql_where=text("email IS NOT NULL"),
        ),
        CheckConstraint(
            # `csv_import` is deliberately absent from VALID_SOURCES: that tuple
            # drives the per-tenant toggles for *scrapeable* sources, and an
            # import is not something you schedule.
            "source IN ('serper', 'company_site', 'linkedin_proxycurl', "
            "'social_profiles', 'csv_import')",
            name="ck_lead_source",
        ),
    )
