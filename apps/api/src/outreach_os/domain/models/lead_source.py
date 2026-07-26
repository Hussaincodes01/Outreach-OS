"""Per-tenant configuration of which lead sources are enabled.

The `source` enum matches the scraping service's supported backends. The
`config` JSONB blob holds source-specific knobs (e.g. for `serper`:
`{"gl": "us", "hl": "en"}`).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP, Boolean

from outreach_os.core.db import Base


class LeadSourceKind(str, Enum):
    SERPER = "serper"
    COMPANY_SITE = "company_site"
    LINKEDIN_PROXYCURL = "linkedin_proxycurl"
    SOCIAL_PROFILES = "social_profiles"


class LeadSource(Base):
    __tablename__ = "lead_source"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    last_run_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_lead_source_tenant", "tenant_id"),
        Index(
            "uq_lead_source_tenant_source",
            "tenant_id",
            "source",
            unique=True,
        ),
        CheckConstraint(
            "source IN ('serper', 'company_site', 'linkedin_proxycurl', 'social_profiles')",
            name="ck_lead_source_kind",
        ),
    )
