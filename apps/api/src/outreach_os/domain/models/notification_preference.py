"""Per-tenant notification preferences.

One row per (tenant, event_key). If no row exists, the `NotificationService`
falls back to safe defaults (in_app=True, email_digest=False, slack=False).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from outreach_os.core.db import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preference"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_key", name="uq_pref_tenant_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_key: Mapped[str] = mapped_column(Text, nullable=False)
    channel_in_app: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    channel_email_digest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    channel_slack: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = ["NotificationPreference"]
