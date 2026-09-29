"""One account per email address, across every workspace.

Login and password reset resolve an email across all tenants through
`auth_user_by_email`, which returns an arbitrary matching row. Until now the
only uniqueness was (tenant_id, email), so a second signup with the same
address (anyone typing a victim's unverified email) created a second account
that login and reset links could land on instead of the real owner's.

The index is on lower(email) so a case variant cannot slip past it.

Existing duplicates are NOT resolved automatically: deciding which of two
accounts is the real owner is a human call. The migration refuses to run
until they are merged or removed by hand.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019_unique_user_email"
down_revision: str | None = "0018_platform_admin"
branch_labels: str | None = None
depends_on: str | None = None

_INDEX = "uq_app_user_email_lower"
_FIND_DUPLICATES = (
    "SELECT lower(email), count(*) FROM app_user GROUP BY 1 HAVING count(*) > 1"
)


def upgrade() -> None:
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM ("
            "  SELECT lower(email) FROM app_user GROUP BY lower(email) HAVING count(*) > 1"
            ") AS d"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(
            f"Cannot create {_INDEX}: {duplicates} email address(es) belong to more "
            f"than one app_user row. Find them with `{_FIND_DUPLICATES}`, merge or "
            "remove the extra accounts by hand, then re-run the migration."
        )
    op.create_index(_INDEX, "app_user", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="app_user")
