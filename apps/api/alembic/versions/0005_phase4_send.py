"""Phase 4 — Send + Reply + Follow-up engine.

Adds 6 tables:
- sequence_run       (a tenant's run of a campaign over a lead cohort)
- sequence_step      (per-lead progress through the campaign's steps)
- send               (an actual email fired by a sequence_step; FK to draft)
- reply              (inbound reply on a send; classified by the LLM)
- tracking_event     (open/click hits; one row per event, type-tagged)
- suppression        (per-tenant email blocklist: unsubscribe / bounce / complaint)

All multi-tenant tables get ENABLE + FORCE RLS + the standard
`tenant_isolation_<table>` policy.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase4_send"
down_revision: str | None = "0004_phase3_agent"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- sequence_run ---
    op.create_table(
        "sequence_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("stopped_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("stopped_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('running', 'paused', 'stopped', 'completed')",
            name="ck_sequence_run_status",
        ),
    )
    op.create_index("ix_sequence_run_tenant", "sequence_run", ["tenant_id"])
    op.create_index("ix_sequence_run_campaign", "sequence_run", ["campaign_id"])
    op.create_index(
        "uq_sequence_run_tenant_name", "sequence_run", ["tenant_id", "name"], unique=True
    )

    # --- sequence_step ---
    op.create_table(
        "sequence_step",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sequence_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_step_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("campaign_step.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("draft.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_reply_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'sent', 'replied', "
            "'stopped', 'failed', 'skipped')",
            name="ck_sequence_step_status",
        ),
        sa.UniqueConstraint(
            "run_id", "lead_id", "campaign_step_id", name="uq_sequence_step_run_lead_step"
        ),
    )
    op.create_index("ix_sequence_step_tenant", "sequence_step", ["tenant_id"])
    op.create_index("ix_sequence_step_run", "sequence_step", ["run_id"])
    op.create_index("ix_sequence_step_scheduled", "sequence_step", ["scheduled_at"])
    op.create_index("ix_sequence_step_status", "sequence_step", ["status"])

    # --- send ---
    op.create_table(
        "send",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sequence_step.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mailbox_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("mailbox.id", ondelete="SET NULL"), nullable=True),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("draft.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_email", postgresql.CITEXT(), nullable=False),
        sa.Column("from_email", postgresql.CITEXT(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("message_id_header", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'bounced', 'failed', 'unsubscribed', 'skipped')",
            name="ck_send_status",
        ),
    )
    op.create_index("ix_send_tenant", "send", ["tenant_id"])
    op.create_index("ix_send_step", "send", ["step_id"])
    op.create_index("ix_send_message_id", "send", ["message_id_header"], unique=True)
    op.create_index("ix_send_to_email", "send", ["tenant_id", "to_email"])
    op.create_index("ix_send_status", "send", ["status"])

    # --- reply ---
    op.create_table(
        "reply",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("send_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("send.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id_header", sa.Text(), nullable=False),
        sa.Column("from_email", postgresql.CITEXT(), nullable=False),
        sa.Column("from_name", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("classification", sa.Text(), nullable=True),
        sa.Column("classification_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("classified_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("classification_trace", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "classification IN ('positive', 'negative', 'ooo', 'question', "
            "'unsubscribe', 'bounce', 'other')",
            name="ck_reply_classification",
        ),
    )
    op.create_index("ix_reply_tenant", "reply", ["tenant_id"])
    op.create_index("ix_reply_send", "reply", ["send_id"])
    op.create_index(
        "uq_reply_message_id", "reply", ["message_id_header"], unique=True
    )
    op.create_index("ix_reply_classification", "reply", ["classification"])

    # --- tracking_event ---
    op.create_table(
        "tracking_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("send_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("send.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "event_type IN ('open', 'click')", name="ck_tracking_event_type"
        ),
    )
    op.create_index("ix_tracking_event_tenant", "tracking_event", ["tenant_id"])
    op.create_index("ix_tracking_event_send", "tracking_event", ["send_id"])
    op.create_index("ix_tracking_event_type", "tracking_event", ["event_type"])

    # --- suppression ---
    op.create_table(
        "suppression",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "reason IN ('unsubscribe', 'bounce', 'complaint', 'manual')",
            name="ck_suppression_reason",
        ),
    )
    op.create_index("ix_suppression_tenant", "suppression", ["tenant_id"])
    op.create_index(
        "uq_suppression_tenant_email", "suppression", ["tenant_id", "email"], unique=True
    )

    # --- Row-Level Security (FORCE on every multi-tenant table) ---
    for table in (
        "sequence_run",
        "sequence_step",
        "send",
        "reply",
        "tracking_event",
        "suppression",
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
        "suppression",
        "tracking_event",
        "reply",
        "send",
        "sequence_step",
        "sequence_run",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("suppression")
    op.drop_table("tracking_event")
    op.drop_table("reply")
    op.drop_table("send")
    op.drop_table("sequence_step")
    op.drop_table("sequence_run")
