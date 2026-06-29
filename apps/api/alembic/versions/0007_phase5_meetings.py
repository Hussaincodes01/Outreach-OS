"""Phase 5 \u2014 Meeting Booking + CRM Sync.

Adds 3 tables:
- meeting              (a proposed/confirmed/declined meeting with 3 slot options)
- crm_connection       (per-tenant CRM config: provider + spreadsheet_id + token ref)
- crm_sync_event       (log of every CRM sync attempt for auditability)

All multi-tenant tables get ENABLE + FORCE RLS + the standard
`tenant_isolation_<table>` policy.

The `meeting.ics_uid` is globally unique (used for the iCalendar UID) so
clients can recognise updates to the same event across syncs.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_phase5_meetings"
down_revision: str | None = "0006_send_created_at"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- meeting ---
    op.create_table(
        "meeting",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mailbox_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("mailbox.id", ondelete="SET NULL"), nullable=True),
        sa.Column("send_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("send.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reply_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("reply.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("agenda", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("proposed_slots", postgresql.JSONB(), nullable=False),
        sa.Column("chosen_slot", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column("provider_event_id", sa.Text(), nullable=True),
        sa.Column("ics_uid", sa.Text(), nullable=False),
        sa.Column("ics_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("organizer_email", postgresql.CITEXT(), nullable=False),
        sa.Column("attendee_email", postgresql.CITEXT(), nullable=False),
        sa.Column("proposed_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("declined_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('proposed', 'confirmed', 'declined', 'cancelled', 'completed', 'no_show')",
            name="ck_meeting_status",
        ),
    )
    op.create_index("ix_meeting_tenant", "meeting", ["tenant_id"])
    op.create_index("ix_meeting_lead", "meeting", ["lead_id"])
    op.create_index("ix_meeting_status", "meeting", ["status"])
    op.create_index(
        "uq_meeting_ics_uid", "meeting", ["ics_uid"], unique=True
    )

    # --- crm_connection ---
    op.create_table(
        "crm_connection",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("spreadsheet_id", sa.Text(), nullable=True),
        sa.Column("sheet_range", sa.Text(), nullable=True, server_default="A:Z"),
        sa.Column("column_mapping", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("access_token_credential_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("credential.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_sync_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "provider IN ('google_sheets')",
            name="ck_crm_connection_provider",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'error')",
            name="ck_crm_connection_status",
        ),
    )
    op.create_index("ix_crm_connection_tenant", "crm_connection", ["tenant_id"])
    op.create_index(
        "uq_crm_connection_tenant_name", "crm_connection",
        ["tenant_id", "name"], unique=True
    )

    # --- crm_sync_event ---
    op.create_table(
        "crm_sync_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crm_connection_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("crm_connection.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("meeting.id", ondelete="CASCADE"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("row_written", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_crm_sync_event_status",
        ),
    )
    op.create_index("ix_crm_sync_event_tenant", "crm_sync_event", ["tenant_id"])
    op.create_index("ix_crm_sync_event_meeting", "crm_sync_event", ["meeting_id"])
    op.create_index("ix_crm_sync_event_status", "crm_sync_event", ["status"])

    # --- Row-Level Security (FORCE on every multi-tenant table) ---
    for table in ("meeting", "crm_connection", "crm_sync_event"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id::text = current_setting('app.current_tenant', true));
            """
        )


def downgrade() -> None:
    for table in ("crm_sync_event", "crm_connection", "meeting"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("crm_sync_event")
    op.drop_table("crm_connection")
    op.drop_table("meeting")
