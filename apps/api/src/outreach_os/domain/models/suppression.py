"""Suppression — per-tenant email blocklist (unsubscribe / bounce / complaint).

Honoured by the SendService: any address in this list is filtered out
before queue. CAN-SPAM and GDPR require us to honour unsubscribes
immediately and globally for the tenant.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class Suppression(Base):
    __tablename__ = "suppression"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_suppression_tenant", "tenant_id"),
        Index("uq_suppression_tenant_email", "tenant_id", "email", unique=True),
        CheckConstraint(
            "reason IN ('unsubscribe', 'bounce', 'complaint', 'manual')",
            name="ck_suppression_reason",
        ),
    )
