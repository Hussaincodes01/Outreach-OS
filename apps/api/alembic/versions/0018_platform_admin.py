"""Platform staff flag.

Marks the operator's own accounts, distinct from `role` which is a user's
position INSIDE a tenant. A tenant owner must never gain visibility of other
customers, so this cannot be derived from role.

There is deliberately no API that sets this column. Granting platform-wide
access to every customer's data is a database-level act, done knowingly:

    UPDATE app_user SET is_platform_admin = true WHERE email = 'you@company.com';
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018_platform_admin"
down_revision: str | None = "0017_social_lookup_helper"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Partial index: the table is overwhelmingly non-admins, and every admin
    # request filters on this being true.
    op.create_index(
        "ix_app_user_platform_admin",
        "app_user",
        ["is_platform_admin"],
        postgresql_where=sa.text("is_platform_admin"),
    )


def downgrade() -> None:
    op.drop_index("ix_app_user_platform_admin", table_name="app_user")
    op.drop_column("app_user", "is_platform_admin")
