"""Phase 6 \u2014 Audit Log + Notifications.

Adds 3 tables:

- notification
    In-app notification feed ("new positive reply", "meeting booked",
    "campaign error", "send failed", "CRM sync failed"). Backed by a
    tenant-isolated append-only feed that the dashboard subscribes to
    via a WebSocket channel.

- notification_preference
    Per-tenant toggle table for which events fire which channels
    (in_app / email_digest / slack). One row per (tenant, event_key).

- slack_webhook
    Per-tenant Slack incoming-webhook URL (Phase 1 vault encrypts it).
    One row per tenant; status=active|paused|error.

All three tables get ENABLE + FORCE RLS + the standard
`tenant_isolation_<table>` policy.

The audit log table is *not* touched here \u2014 it already exists from
Phase 0+1 with a hash chain. This phase adds the JSON export endpoint
and a `payload_index` GIN index so the dashboard's filter bar can
search payloads.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_phase6_notifications"
down_revision: str | None = "0007_phase5_meetings"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- notification ---
    op.create_table(
        "notification",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="info"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivered_in_app", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("delivered_email", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("delivered_slack", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "severity IN ('info', 'success', 'warning', 'error')",
            name="ck_notification_severity",
        ),
    )
    op.create_index("ix_notification_tenant", "notification", ["tenant_id"])
    op.create_index("ix_notification_event", "notification", ["event_key"])
    op.create_index("ix_notification_unread", "notification",
                    ["tenant_id", "read_at"],
                    postgresql_where=sa.text("read_at IS NULL"))
    op.create_index("ix_notification_created", "notification",
                    ["tenant_id", sa.text("created_at DESC")])

    # --- notification_preference ---
    op.create_table(
        "notification_preference",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("channel_in_app", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("channel_email_digest", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("channel_slack", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "event_key", name="uq_pref_tenant_event"),
    )
    op.create_index("ix_notification_preference_tenant",
                    "notification_preference", ["tenant_id"])

    # --- slack_webhook ---
    op.create_table(
        "slack_webhook",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False, server_default="default"),
        sa.Column("webhook_url_credential_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("credential.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'error')",
            name="ck_slack_webhook_status",
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_slack_webhook_tenant_name"),
    )
    op.create_index("ix_slack_webhook_tenant", "slack_webhook", ["tenant_id"])

    # --- audit_event payload search index ---
    op.create_index(
        "ix_audit_event_payload_gin",
        "audit_event", ["payload"],
        postgresql_using="gin",
        postgresql_ops={"payload": "jsonb_path_ops"},
    )

    # --- Row-Level Security (FORCE on every multi-tenant table) ---
    for table in ("notification", "notification_preference", "slack_webhook"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id::text = current_setting('app.current_tenant', true));
            """
        )


def downgrade() -> None:
    for table in ("slack_webhook", "notification_preference", "notification"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_audit_event_payload_gin", table_name="audit_event")
    op.drop_table("slack_webhook")
    op.drop_table("notification_preference")
    op.drop_table("notification")
