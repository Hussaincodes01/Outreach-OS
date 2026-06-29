"""Knowledge base item — a raw case study / past win / testimonial.

A tenant uploads text snippets that the LangGraph RAG pipeline chunks,
embeds, and retrieves at draft-generation time. The body is plain text;
the tenant can paste from anywhere.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class KnowledgeBaseItem(Base):
    __tablename__ = "knowledge_base_item"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_kb_item_tenant", "tenant_id"),
        CheckConstraint("char_length(title) > 0", name="ck_kb_item_title_nonempty"),
        CheckConstraint("char_length(body) > 0", name="ck_kb_item_body_nonempty"),
    )
