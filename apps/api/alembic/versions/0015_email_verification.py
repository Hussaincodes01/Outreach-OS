"""Track email verification on app_user.

NULL means unverified. Existing users are backfilled as verified: they
predate the feature and locking them out of their own accounts to enforce a
rule introduced after they signed up would be indefensible.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0015_email_verification"
down_revision: str | None = "0014_lead_csv_import_source"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("email_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Grandfather everyone who already had an account.
    op.execute("UPDATE app_user SET email_verified_at = created_at")


def downgrade() -> None:
    op.drop_column("app_user", "email_verified_at")
