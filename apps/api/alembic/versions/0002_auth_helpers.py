"""SECURITY DEFINER helpers for cross-tenant operations.

The login flow needs to look up an `app_user` by email across all tenants,
which is impossible under the RLS policy (no GUC = no rows). We expose a
single function that runs as its owner (the migration user, which has the
necessary privileges) and returns only the minimum information needed
to authenticate: (tenant_id, password_hash).

The function is STABLE so the planner can cache the result within a
single statement, and SECURITY INVOKER is the default; we use DEFINER so
RLS doesn't filter the lookup.
"""
from __future__ import annotations

from alembic import op


revision = "0002_auth_helpers"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_user_by_email(p_email text)
        RETURNS TABLE(tenant_id uuid, user_id uuid, password_hash text, role text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        AS $$
            SELECT u.tenant_id, u.id, u.password_hash, u.role
            FROM app_user u
            WHERE u.email = lower(p_email)
              AND u.is_active = true
            LIMIT 1
        $$;
        """
    )
    # Lock down EXECUTE to the application role only. Revoke from PUBLIC so
    # other roles (e.g. a future BI role) cannot use it as a backdoor.
    op.execute("REVOKE ALL ON FUNCTION auth_user_by_email(text) FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_user_by_email(text)")
