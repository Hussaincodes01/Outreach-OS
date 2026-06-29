"""Knowledge base chunk — a token-bounded segment of a knowledge_base_item
with its embedding vector. Indexed with pgvector (HNSW, cosine distance).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base

# Embedding dimensionality. Must match `Settings.llm_embedding_dimensions`.
EMBEDDING_DIM = 1536


class KnowledgeBaseChunk(Base):
    __tablename__ = "knowledge_base_chunk"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_base_item.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("ix_kb_chunk_tenant", "tenant_id"),
        Index("ix_kb_chunk_item", "item_id"),
        Index("uq_kb_chunk_item_index", "item_id", "chunk_index", unique=True),
        CheckConstraint("chunk_index >= 0", name="ck_kb_chunk_index_nonneg"),
    )
