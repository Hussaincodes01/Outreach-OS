"""Per-tenant Slack incoming-webhook configuration.

The webhook URL is stored in a Phase 1 `Credential` (encrypted at rest
with the tenant's Fernet key). This row holds the *pointer* and
delivery state.

Why a separate credential? So that the URL never appears in any
log line / audit payload in plaintext. Test code that wants to
synthesise a webhook can use the StubSlackClient directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from outreach_os.core.db import Base


class SlackWebhook(Base):
    __tablename__ = "slack_webhook"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'error')",
            name="ck_slack_webhook_status",
        ),
        UniqueConstraint("tenant_id", "name", name="uq_slack_webhook_tenant_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    webhook_url_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credential.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = ["SlackWebhook"]
