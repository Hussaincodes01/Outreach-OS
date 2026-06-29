"""Phase 7 \u2014 Billing + Plans.

Adds 4 tables:

- plan
    Master list of plan tiers. Seeded by migration with
    Starter / Growth / Scale. Read-only via API; managed by us.

- subscription
    A tenant's currently-active subscription. There is at most one
    active subscription per tenant (enforced by partial unique index).
    We track Stripe IDs (or local fake IDs when running in dev mode).

- usage_event
    Per-tenant metered usage: sends, leads_scraped, llm_tokens_in,
    llm_tokens_out. Written by the same services that perform the
    work (send, scraping, agent). Aggregated by `services.billing.rollup`
    to update Tenant.month_usage counters.

- billing_portal_token
    Short-lived (1h) bearer token for the in-app billing portal.
    Avoids needing to re-auth the user to Stripe's portal.

All multi-tenant tables get ENABLE + FORCE RLS + the standard
`tenant_isolation_<table>` policy.

The `plan` table is global (no tenant_id); it's read-only and shared.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_phase7_billing"
down_revision: str | None = "0008_phase6_notifications"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # --- plan ---
    op.create_table(
        "plan",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("monthly_price_cents", sa.Integer(), nullable=False),
        sa.Column("monthly_send_cap", sa.Integer(), nullable=False),
        sa.Column("monthly_lead_cap", sa.Integer(), nullable=False),
        sa.Column("monthly_llm_token_cap", sa.Integer(), nullable=False),
        sa.Column("crm_sync_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("slack_notifications_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("email_digest_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("max_team_seats", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("max_mailboxes", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("display_order", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # Seed the three default plans.
    op.execute(
        """
        INSERT INTO plan (code, name, monthly_price_cents, monthly_send_cap,
                          monthly_lead_cap, monthly_llm_token_cap,
                          crm_sync_enabled, slack_notifications_enabled,
                          email_digest_enabled, max_team_seats, max_mailboxes,
                          display_order)
        VALUES
          ('starter',  'Starter',  2900,  500,    1000, 200000, false, false, false, 1, 1, 1),
          ('growth',   'Growth',   9900,  5000,   25000, 1500000, true,  true,  true,  5, 10, 2),
          ('scale',    'Scale',    29900, 25000,  100000, 10000000, true, true,  true,  25, 50, 3)
        """
    )

    # --- subscription ---
    op.create_table(
        "subscription",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("plan.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("provider", sa.Text(), nullable=False, server_default="stub"),
        sa.Column("provider_customer_id", sa.Text(), nullable=True),
        sa.Column("provider_subscription_id", sa.Text(), nullable=True),
        sa.Column("current_period_start", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("canceled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('trialing','active','past_due','canceled','incomplete')",
            name="ck_subscription_status",
        ),
        sa.CheckConstraint(
            "provider IN ('stub','stripe')",
            name="ck_subscription_provider",
        ),
    )
    op.create_index("ix_subscription_tenant", "subscription", ["tenant_id"])
    op.create_index("ix_subscription_status", "subscription", ["status"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_subscription_tenant_active
        ON subscription (tenant_id)
        WHERE status IN ('active','trialing','past_due')
        """
    )

    # --- usage_event ---
    op.create_table(
        "usage_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "metric IN ('send','lead_scraped','llm_token_in','llm_token_out')",
            name="ck_usage_event_metric",
        ),
    )
    op.create_index("ix_usage_event_tenant", "usage_event", ["tenant_id"])
    op.create_index("ix_usage_event_tenant_metric", "usage_event",
                    ["tenant_id", "metric"])
    op.create_index("ix_usage_event_created", "usage_event",
                    ["tenant_id", sa.text("created_at DESC")])

    # --- billing_portal_token ---
    op.create_table(
        "billing_portal_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_billing_portal_token_tenant", "billing_portal_token", ["tenant_id"])

    # Add Tenant.month_usage columns so reads don't have to roll up live.
    op.add_column("tenant", sa.Column("month_usage_sends", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.add_column("tenant", sa.Column("month_usage_leads", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.add_column("tenant", sa.Column("month_usage_llm_tokens", sa.Integer(),
                                       nullable=False, server_default="0"))
    op.add_column("tenant", sa.Column("month_usage_reset_at",
                                       sa.TIMESTAMP(timezone=True),
                                       nullable=False,
                                       server_default=sa.text("date_trunc('month', now())")))

    # --- Row-Level Security ---
    # billing_portal_token is the *capability* itself: whoever holds
    # the random token may consume it. We do NOT enable RLS on this
    # table — the token is the auth credential. The short expiry
    # (1h) + single-use (consumed_at) + 32-byte random secret
    # (256 bits of entropy) is the access control.
    for table in ("subscription", "usage_event"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id::text = current_setting('app.current_tenant', true));
            """
        )


def downgrade() -> None:
    for table in ("usage_event", "subscription"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_column("tenant", "month_usage_reset_at")
    op.drop_column("tenant", "month_usage_llm_tokens")
    op.drop_column("tenant", "month_usage_leads")
    op.drop_column("tenant", "month_usage_sends")

    op.drop_table("billing_portal_token")
    op.drop_table("usage_event")
    op.drop_table("subscription")
    op.drop_table("plan")
