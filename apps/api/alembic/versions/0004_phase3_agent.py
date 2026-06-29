"""Phase 3 — LangGraph agent (campaigns + RAG + drafts).

Adds 5 tables:
- campaign            (one per outreach push a tenant wants to run)
- campaign_step       (sequence steps inside a campaign; FK to campaign)
- knowledge_base_item (raw case-study text; FK to tenant)
- knowledge_base_chunk (RAG chunks with pgvector embeddings; FK to item)
- draft               (LLM-generated email for a (lead, step); FK to campaign)
- agent_run           (a single LangGraph invocation; FK to draft)

All multi-tenant tables get ENABLE + FORCE RLS + the standard
`tenant_isolation_<table>` policy.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004_phase3_agent"
down_revision: str | None = "0003_lead_scraping"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- pgvector extension (no-op if already installed in dev compose) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # --- campaign ---
    op.create_table(
        "campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("llm_model", sa.Text(), nullable=True),
        # Style guide: 3 sample emails written by the customer.
        sa.Column("style_sample_emails", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        # Free-form style instructions the customer wants enforced.
        sa.Column("style_notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_campaign_tenant_name"),
        sa.CheckConstraint("char_length(name) > 0", name="ck_campaign_name_nonempty"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name="ck_campaign_status",
        ),
    )
    op.create_index("ix_campaign_tenant", "campaign", ["tenant_id"])

    # --- campaign_step ---
    op.create_table(
        "campaign_step",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False),
        # 1-based ordinal within the campaign.
        sa.Column("step_number", sa.Integer(), nullable=False),
        # Days after the previous step (0 for the first step).
        sa.Column("delay_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("campaign_id", "step_number", name="uq_campaign_step_number"),
        sa.CheckConstraint("step_number >= 1", name="ck_campaign_step_number_positive"),
        sa.CheckConstraint("delay_days >= 0", name="ck_campaign_step_delay_nonneg"),
    )
    op.create_index("ix_campaign_step_tenant", "campaign_step", ["tenant_id"])
    op.create_index("ix_campaign_step_campaign", "campaign_step", ["campaign_id"])

    # --- knowledge_base_item (raw text) ---
    op.create_table(
        "knowledge_base_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("char_length(title) > 0", name="ck_kb_item_title_nonempty"),
        sa.CheckConstraint("char_length(body) > 0", name="ck_kb_item_body_nonempty"),
    )
    op.create_index("ix_kb_item_tenant", "knowledge_base_item", ["tenant_id"])

    # --- knowledge_base_chunk (RAG chunks with embeddings) ---
    # Embedding dim is fixed at 1536 (text-embedding-3-small). If the customer
    # later picks a different model the alembic op to alter this is cheap, but
    # we still pin it here so the index type is known.
    op.create_table(
        "knowledge_base_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_base_item.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("item_id", "chunk_index",
                            name="uq_kb_chunk_item_index"),
    )
    op.create_index("ix_kb_chunk_tenant", "knowledge_base_chunk", ["tenant_id"])
    op.create_index("ix_kb_chunk_item", "knowledge_base_chunk", ["item_id"])
    # HNSW index for fast cosine similarity. Lists=16 is fine for dev/small data.
    op.execute(
        "CREATE INDEX ix_kb_chunk_embedding ON knowledge_base_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # --- draft ---
    op.create_table(
        "draft",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_step.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("s3_key", sa.Text(), nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'approved', 'rejected', 'sent', 'failed')",
            name="ck_draft_status",
        ),
    )
    op.create_index("ix_draft_tenant", "draft", ["tenant_id"])
    op.create_index("ix_draft_campaign", "draft", ["campaign_id"])
    op.create_index("ix_draft_lead", "draft", ["lead_id"])
    # One draft per (lead, step) per campaign — idempotent regeneration.
    op.execute(
        "CREATE UNIQUE INDEX uq_draft_campaign_lead_step "
        "ON draft (campaign_id, lead_id, step_id)"
    )

    # --- agent_run ---
    op.create_table(
        "agent_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("draft.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("trace", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embeddings_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_agent_run_status",
        ),
    )
    op.create_index("ix_agent_run_tenant", "agent_run", ["tenant_id"])
    op.create_index("ix_agent_run_campaign", "agent_run", ["campaign_id"])

    # --- Row-Level Security (FORCE on every multi-tenant table) ---
    for table in (
        "campaign",
        "campaign_step",
        "knowledge_base_item",
        "knowledge_base_chunk",
        "draft",
        "agent_run",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id::text = current_setting('app.current_tenant', true));
            """
        )


def downgrade() -> None:
    for table in (
        "agent_run",
        "draft",
        "knowledge_base_chunk",
        "knowledge_base_item",
        "campaign_step",
        "campaign",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("agent_run")
    op.drop_table("draft")
    op.drop_table("knowledge_base_chunk")
    op.drop_table("knowledge_base_item")
    op.drop_table("campaign_step")
    op.drop_table("campaign")
    # Note: leaving the vector extension in place — other apps may use it.
