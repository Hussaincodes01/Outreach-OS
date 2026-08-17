"""SECURITY DEFINER helpers for the social sign-in flow.

Same problem `auth_user_by_email` solves for passwords: at the moment someone
returns from Google or Microsoft we do not yet know which tenant they belong
to, so there is no GUC to bind and RLS filters every row away. Without these,
the lookup silently finds nothing and the flow tries to create a duplicate
account on every sign-in.

Two functions rather than one:
- by subject, the provider's stable id — the normal returning-user path.
- by email, returning verification state too, so the linking decision can be
  made without a second cross-tenant read.

Both are owned by postgres so SECURITY DEFINER actually bypasses RLS (a
NOBYPASSRLS owner would still be filtered), and EXECUTE is revoked from PUBLIC.
"""
from __future__ import annotations

from alembic import op

revision: str = "0017_social_lookup_helper"
down_revision: str | None = "0016_social_login"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_user_by_subject(
            p_provider text, p_subject text
        )
        RETURNS TABLE(tenant_id uuid, user_id uuid, is_active boolean)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        AS $$
            SELECT u.tenant_id, u.id, u.is_active
            FROM app_user u
            WHERE u.auth_provider = p_provider
              AND u.auth_subject = p_subject
            LIMIT 1
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION auth_user_for_linking(p_email text)
        RETURNS TABLE(tenant_id uuid, user_id uuid, is_active boolean)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        AS $$
            SELECT u.tenant_id, u.id, u.is_active
            FROM app_user u
            WHERE u.email = lower(p_email)
            LIMIT 1
        $$;
        """
    )
    for signature in (
        "auth_user_by_subject(text, text)",
        "auth_user_for_linking(text)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        # SECURITY DEFINER only bypasses RLS when the owner does; the app role
        # is NOBYPASSRLS by design.
        op.execute(f"ALTER FUNCTION {signature} OWNER TO postgres")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO outreach")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_user_by_subject(text, text)")
    op.execute("DROP FUNCTION IF EXISTS auth_user_for_linking(text)")
