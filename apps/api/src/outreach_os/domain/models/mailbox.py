"""Mailbox model — connected sending account."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import CITEXT, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP, Boolean

from outreach_os.core.db import Base


class Mailbox(Base):
    __tablename__ = "mailbox"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    email_address: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    refresh_token_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    smtp_config_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    daily_send_cap: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        CheckConstraint(
            "provider IN ('gmail', 'outlook', 'smtp')", name="ck_mailbox_provider"
        ),
        Index("ix_mailbox_tenant", "tenant_id"),
        Index("uq_mailbox_tenant_email", "tenant_id", "email_address", unique=True),
    )
