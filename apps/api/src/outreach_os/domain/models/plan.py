"""Plan tier definitions.

A plan encodes the limits and feature flags for a subscription tier.
Read-only via API (managed by us). One row per plan code.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from outreach_os.core.db import Base


class Plan(Base):
    __tablename__ = "plan"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    monthly_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_send_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_lead_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_llm_token_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    crm_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    slack_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    email_digest_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_team_seats: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    max_mailboxes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = ["Plan"]
