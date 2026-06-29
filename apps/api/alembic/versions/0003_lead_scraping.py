"""Phase 2 — lead scraping subsystem.

Adds 5 tables: icp, lead_source, lead, scraping_job, proxy.
Every multi-tenant table gets ENABLE + FORCE RLS + the standard
`tenant_isolation_<table>` policy (matching the pattern in 0001_initial).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_lead_scraping"
down_revision: str | None = "0002_auth_helpers"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- icp ---
    op.create_table(
        "icp",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industries", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("company_sizes", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("geos", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("titles", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("signals", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("extra", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_icp_tenant_name"),
        sa.CheckConstraint("char_length(name) > 0", name="ck_icp_name_nonempty"),
    )
    op.create_index("ix_icp_tenant", "icp", ["tenant_id"])

    # --- lead_source ---
    op.create_table(
        "lead_source",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "source", name="uq_lead_source_tenant_source"),
        sa.CheckConstraint(
            "source IN ('serper', 'company_site', 'linkedin_proxycurl')",
            name="ck_lead_source_kind",
        ),
    )
    op.create_index("ix_lead_source_tenant", "lead_source", ["tenant_id"])

    # --- proxy ---
    op.create_table(
        "proxy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False, server_default="http"),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("url_ciphertext", postgresql.BYTEA(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "label", name="uq_proxy_tenant_label"),
        sa.CheckConstraint("protocol IN ('http', 'https', 'socks5')",
                           name="ck_proxy_protocol"),
        sa.CheckConstraint("port > 0 AND port < 65536", name="ck_proxy_port_range"),
    )
    op.create_index("ix_proxy_tenant", "proxy", ["tenant_id"])

    # --- scraping_job ---
    # Note: must be created BEFORE lead, since lead.job_id FKs into it.
    op.create_table(
        "scraping_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("icp_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("icp.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("sources", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_scraping_job_status",
        ),
        sa.CheckConstraint("requested_count >= 1", name="ck_scraping_job_requested_positive"),
    )
    op.create_index("ix_scraping_job_tenant", "scraping_job", ["tenant_id"])
    op.create_index("ix_scraping_job_status", "scraping_job", ["tenant_id", "status"])

    # --- lead ---
    op.create_table(
        "lead",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("scraping_job.id", ondelete="SET NULL"), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("company_size", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "source IN ('serper', 'company_site', 'linkedin_proxycurl')",
            name="ck_lead_source",
        ),
    )
    op.create_index("ix_lead_tenant", "lead", ["tenant_id"])
    op.create_index("ix_lead_tenant_source", "lead", ["tenant_id", "source"])
    op.create_index("ix_lead_tenant_job", "lead", ["tenant_id", "job_id"])
    # Partial unique index on (tenant_id, email) — the primary dedup key.
    # We deliberately do NOT dedup on (tenant_id, domain): a customer can
    # legitimately have multiple contacts at the same company (think
    # "VP Sales" and "Head of Marketing" both at Acme). The email index
    # alone is the race safety net.
    op.execute(
        "CREATE UNIQUE INDEX uq_lead_tenant_email "
        "ON lead (tenant_id, email) WHERE email IS NOT NULL"
    )

    # --- Row-Level Security (FORCE on every multi-tenant table) ---
    for table in ("icp", "lead_source", "proxy", "scraping_job", "lead"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id::text = current_setting('app.current_tenant', true));
            """
        )


def downgrade() -> None:
    for table in ("icp", "lead_source", "proxy", "scraping_job", "lead"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("lead")
    op.drop_table("scraping_job")
    op.drop_table("proxy")
    op.drop_table("lead_source")
    op.drop_table("icp")
