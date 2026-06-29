"""Initial schema with multi-tenant Row-Level Security + append-only audit.

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")
    # pgvector is needed for Phase 3 RAG; install now so the schema can reference it later.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # --- tenant ---
    op.create_table(
        "tenant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("plan", sa.Text(), nullable=False, server_default="free"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    # --- app_user ---
    op.create_table(
        "app_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "email", name="uq_app_user_tenant_email"),
    )
    op.create_index("ix_app_user_tenant", "app_user", ["tenant_id"])

    # --- credential ---
    op.create_table(
        "credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("ciphertext", postgresql.BYTEA(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_credential_tenant_kind", "credential", ["tenant_id", "kind"])

    # --- mailbox ---
    op.create_table(
        "mailbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("email_address", postgresql.CITEXT(), nullable=False),
        sa.Column("refresh_token_ciphertext", postgresql.BYTEA(), nullable=True),
        sa.Column("smtp_config_ciphertext", postgresql.BYTEA(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("daily_send_cap", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "email_address", name="uq_mailbox_tenant_email"),
    )
    op.create_index("ix_mailbox_tenant", "mailbox", ["tenant_id"])

    # --- audit_event (append-only, hash-chained) ---
    op.create_table(
        "audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("prev_hash", postgresql.BYTEA(), nullable=True),
        sa.Column("row_hash", postgresql.BYTEA(), nullable=True),
    )
    op.create_index("ix_audit_tenant_time", "audit_event",
                    ["tenant_id", sa.text("created_at DESC")])
    op.create_index("ix_audit_action", "audit_event", ["action"])

    # --- append-only enforcement ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_block_modify() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_event is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_no_update
        BEFORE UPDATE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION audit_block_modify();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_event_no_delete
        BEFORE DELETE ON audit_event
        FOR EACH ROW EXECUTE FUNCTION audit_block_modify();
        """
    )

    # --- Row-Level Security ---
    # We enable RLS on every multi-tenant table. The application sets
    # app.current_tenant at the start of every request transaction; the
    # RLS policies use current_setting('app.current_tenant', true) to filter.
    #
    # CRITICAL: table owners BYPASS RLS by default. We must FORCE RLS so
    # the policy is enforced even for the role that owns the tables.
    # (For production, the app role should be a non-owner; for dev we
    # FORCE on the owner so the safety net works either way.)
    for table in ("app_user", "credential", "mailbox", "audit_event"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id::text = current_setting('app.current_tenant', true));
            """
        )

    # Note: the 'tenant' table itself is master and is NOT under RLS; access
    # is gated by the API layer (only superuser code or an explicit query by
    # an authenticated owner user touching their own tenant row).


def downgrade() -> None:
    for table in ("app_user", "credential", "mailbox", "audit_event"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP TRIGGER IF EXISTS audit_event_no_delete ON audit_event;")
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_update ON audit_event;")
    op.execute("DROP FUNCTION IF EXISTS audit_block_modify();")

    op.drop_table("audit_event")
    op.drop_table("mailbox")
    op.drop_table("credential")
    op.drop_table("app_user")
    op.drop_table("tenant")
