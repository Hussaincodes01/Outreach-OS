"""CrmConnection \u2014 per-tenant CRM integration config.

V1 supports Google Sheets only (OAuth token already wired in Phase 1).
The `access_token_credential_id` points at the encrypted credential row
that holds the OAuth refresh token (we re-mint access tokens on demand).
`column_mapping` is a JSON dict mapping Outreach OS lead fields
(\"first_name\", \"email\", \"company_name\") to the spreadsheet column letter
(\"A\", \"B\", \"C\").
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class CrmConnection(Base):
    __tablename__ = "crm_connection"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    spreadsheet_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sheet_range: Mapped[str | None] = mapped_column(Text, nullable=True, server_default="A:Z")
    column_mapping: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    access_token_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("credential.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    last_sync_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_crm_connection_tenant", "tenant_id"),
        Index("uq_crm_connection_tenant_name", "tenant_id", "name", unique=True),
        CheckConstraint(
            "provider IN ('google_sheets')",
            name="ck_crm_connection_provider",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'error')",
            name="ck_crm_connection_status",
        ),
    )
