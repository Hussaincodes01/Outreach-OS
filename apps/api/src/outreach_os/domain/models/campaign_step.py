"""CampaignStep — one step in a campaign's outreach sequence.

A typical campaign has 1..N steps. Step #1 is the opener (delay_days=0).
Step #2+ is a follow-up scheduled `delay_days` after the previous step.
Each step defines the subject template and the goal (what the email is
trying to achieve) — the LangGraph draft node uses both to compose the body.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class CampaignStep(Base):
    __tablename__ = "campaign_step"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaign.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    campaign: Mapped[Campaign] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Campaign",
        back_populates="steps",
    )

    __table_args__ = (
        Index("ix_campaign_step_tenant", "tenant_id"),
        Index("ix_campaign_step_campaign", "campaign_id"),
        Index("uq_campaign_step_number", "campaign_id", "step_number", unique=True),
        CheckConstraint("step_number >= 1", name="ck_campaign_step_number_positive"),
        CheckConstraint("delay_days >= 0", name="ck_campaign_step_delay_nonneg"),
    )
