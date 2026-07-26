"""Per-tenant embedding model.

Separate from `default_llm_model` because most providers ship no embeddings
API. A workspace can therefore draft on Anthropic or Ollama while still
pointing the knowledge base at an embedding-capable provider.

Only models producing 1536 dimensions are selectable — `knowledge_base_chunk`
.embedding is a fixed `Vector(1536)` column.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013_tenant_embedding_model"
down_revision: str | None = "0012_byok_and_onboarding"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("embedding_llm_model", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant", "embedding_llm_model")
