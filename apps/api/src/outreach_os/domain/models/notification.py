"""In-app notification feed.

A `Notification` is a single point-in-time event surfaced to the user's
dashboard ("new positive reply", "meeting booked", "send failed",
"campaign error"). It can be fanned out to multiple channels (in-app,
email digest, Slack) but the row itself is the source of truth \u2014 the
channel-delivery flags are updated as the worker hits each.

Use cases:
- Dashboard: list unread + mark-read.
- WebSocket: subscribe to `notification.created` events.
- Digest: nightly Celery beat picks up unread `channel_email_digest`
  notifications and groups them.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from outreach_os.core.db import Base


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'success', 'warning', 'error')",
            name="ck_notification_severity",
        ),
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
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="info")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_in_app: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    delivered_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    delivered_slack: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# Phase 6 unread partial index: tenant_id + read_at IS NULL
Index(
    "ix_notification_unread",
    Notification.tenant_id,
    Notification.read_at,
    postgresql_where=text("read_at IS NULL"),
)


__all__ = ["Notification"]
