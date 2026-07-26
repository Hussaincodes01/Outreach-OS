"""Add social_profiles as a valid lead source.

Updates the CHECK constraints on `lead_source` and `lead` tables
to accept 'social_profiles' as a source value.
"""
from __future__ import annotations

from alembic import op

revision: str = "0011_add_social_profiles_source"
down_revision: str | None = "0010_fix_auth_function_rls"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE lead_source DROP CONSTRAINT IF EXISTS ck_lead_source_kind"
    )
    op.execute(
        "ALTER TABLE lead_source ADD CONSTRAINT ck_lead_source_kind "
        "CHECK (source IN ('serper', 'company_site', 'linkedin_proxycurl', 'social_profiles'))"
    )
    op.execute(
        "ALTER TABLE lead DROP CONSTRAINT IF EXISTS ck_lead_source"
    )
    op.execute(
        "ALTER TABLE lead ADD CONSTRAINT ck_lead_source "
        "CHECK (source IN ('serper', 'company_site', 'linkedin_proxycurl', 'social_profiles'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE lead_source DROP CONSTRAINT IF EXISTS ck_lead_source_kind"
    )
    op.execute(
        "ALTER TABLE lead_source ADD CONSTRAINT ck_lead_source_kind "
        "CHECK (source IN ('serper', 'company_site', 'linkedin_proxycurl'))"
    )
    op.execute(
        "ALTER TABLE lead DROP CONSTRAINT IF EXISTS ck_lead_source"
    )
    op.execute(
        "ALTER TABLE lead ADD CONSTRAINT ck_lead_source "
        "CHECK (source IN ('serper', 'company_site', 'linkedin_proxycurl'))"
    )
