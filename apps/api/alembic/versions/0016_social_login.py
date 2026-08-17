"""Track how a user authenticates.

`auth_provider` is 'password' for existing accounts. `auth_subject` holds the
provider's stable user id: email addresses get reassigned inside a company,
the subject does not, so it is what we match on when someone signs in again.

`password_hash` stays NOT NULL. SSO-only users get an unusable random hash
rather than a nullable column, so there is no code path where an empty or
NULL hash could ever be treated as "matches anything".
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016_social_login"
down_revision: str | None = "0015_email_verification"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "auth_provider",
            sa.Text(),
            nullable=False,
            server_default="password",
        ),
    )
    op.add_column("app_user", sa.Column("auth_subject", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_app_user_auth_provider",
        "app_user",
        "auth_provider IN ('password', 'google', 'microsoft')",
    )
    # One account per provider subject. Partial so the many password users
    # with NULL subjects don't collide.
    op.create_index(
        "uq_app_user_auth_subject",
        "app_user",
        ["auth_provider", "auth_subject"],
        unique=True,
        postgresql_where=sa.text("auth_subject IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_app_user_auth_subject", table_name="app_user")
    op.drop_constraint("ck_app_user_auth_provider", "app_user", type_="check")
    op.drop_column("app_user", "auth_subject")
    op.drop_column("app_user", "auth_provider")
