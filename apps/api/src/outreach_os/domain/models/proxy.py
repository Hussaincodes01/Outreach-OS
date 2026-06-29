"""Per-tenant proxy config (optional).

Customers bring their own residential proxies — best practice for outreach
tools so the customer's IPs don't all come from a single ASN. The
`url_ciphertext` blob holds the entire proxy URL (with optional
username/password) encrypted with the per-tenant DEK.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Boolean, TIMESTAMP

from outreach_os.core.db import Base


class Proxy(Base):
    __tablename__ = "proxy"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False, server_default="http")
    host: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    url_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_proxy_tenant", "tenant_id"),
        Index("uq_proxy_tenant_label", "tenant_id", "label", unique=True),
        CheckConstraint("protocol IN ('http', 'https', 'socks5')", name="ck_proxy_protocol"),
        CheckConstraint("port > 0 AND port < 65536", name="ck_proxy_port_range"),
    )
