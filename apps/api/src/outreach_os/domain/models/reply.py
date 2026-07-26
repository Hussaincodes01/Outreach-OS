"""Reply — inbound email reply on a Send.

Classified by the LLM into one of: positive / negative / ooo / question /
unsubscribe / bounce / other. `message_id_header` is RFC5322 In-Reply-To or
References — used to dedup (Gmail can deliver duplicates of the same reply).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base

if TYPE_CHECKING:
    from outreach_os.domain.models.send import Send



class Reply(Base):
    __tablename__ = "reply"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    send_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("send.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id_header: Mapped[str] = mapped_column(Text, nullable=False)
    from_email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    from_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    classification: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=4, scale=3), nullable=True
    )
    classified_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    classification_trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    send: Mapped[Send] = relationship(
        "Send", back_populates="replies"
    )

    __table_args__ = (
        Index("ix_reply_tenant", "tenant_id"),
        Index("ix_reply_send", "send_id"),
        Index("uq_reply_message_id", "message_id_header", unique=True),
        Index("ix_reply_classification", "classification"),
        CheckConstraint(
            "classification IN ('positive', 'negative', 'ooo', 'question', "
            "'unsubscribe', 'bounce', 'other') OR classification IS NULL",
            name="ck_reply_classification",
        ),
    )
