"""Tenant subscription.

There is at most one *active* subscription per tenant (enforced by a
partial unique index). Free tenants don't have a row until they
upgrade; the implicit plan is the `starter` defaults.

`provider` is `stripe` in production and `stub` in dev/test.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from outreach_os.core.db import Base


class Subscription(Base):
    __tablename__ = "subscription"
    __table_args__ = (
        CheckConstraint(
            "status IN ('trialing','active','past_due','canceled','incomplete')",
            name="ck_subscription_status",
        ),
        CheckConstraint(
            "provider IN ('stub','stripe')",
            name="ck_subscription_provider",
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
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="stub")
    provider_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


Index(
    "uq_subscription_tenant_active",
    Subscription.tenant_id,
    postgresql_where=text("status IN ('active','trialing','past_due')"),
    unique=True,
)


__all__ = ["Subscription"]
