"""Fix auth_user_by_email to bypass RLS.

The `auth_user_by_email` function was created with SECURITY DEFINER but
owned by the `outreach` app role, which has NOBYPASSRLS. In PostgreSQL,
SECURITY DEFINER does NOT bypass RLS unless the owner has BYPASSRLS
(see https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

This was a bug: the original migration 0002 intended the function to
perform cross-tenant lookups for the login flow, but RLS silently
blocked every query (current_setting with `true` returns NULL when
`app.current_tenant` is unset, so the RLS policy never matched).

The fix: change ownership to `postgres` (the bootstrap superuser, which
has implicit BYPASSRLS) so SECURITY DEFINER actually works. We then
re-grant EXECUTE to `outreach` (ALTER OWNER drops existing ACLs).

Note: this migration MUST run as a superuser (postgres), not the regular
app role. In the test suite (conftest.py) the fix is applied separately
via the admin connection for the same reason.
"""
from __future__ import annotations

from alembic import op

revision = "0010_fix_auth_function_rls"
down_revision = "0009_phase7_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The function must be owned by a superuser role so SECURITY DEFINER
    # bypasses RLS. ALTER OWNER requires superuser privileges — this
    # migration must run as the bootstrap superuser (postgres), not the
    # app role (outreach).
    op.execute("ALTER FUNCTION auth_user_by_email(text) OWNER TO postgres")
    # ALTER OWNER drops existing ACLs; re-grant EXECUTE to the app role.
    op.execute("GRANT ALL ON FUNCTION auth_user_by_email(text) TO outreach")


def downgrade() -> None:
    op.execute("REVOKE ALL ON FUNCTION auth_user_by_email(text) FROM outreach")
    op.execute("ALTER FUNCTION auth_user_by_email(text) OWNER TO outreach")
    op.execute("GRANT ALL ON FUNCTION auth_user_by_email(text) TO outreach")
