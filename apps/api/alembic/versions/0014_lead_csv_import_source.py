"""Allow `csv_import` as a lead source.

Leads could previously only originate from the scraping pipeline, which needs a
paid Serper or Proxycurl key — so a customer arriving with their own list had
no way in at all.

Only `lead.source` is widened. `lead_source` holds the per-tenant toggles for
*scrapeable* sources and is autoseeded from VALID_SOURCES; an import is not
something you schedule or enable, so it does not belong there.
"""
from __future__ import annotations

from alembic import op

revision: str = "0014_lead_csv_import_source"
down_revision: str | None = "0013_tenant_embedding_model"
branch_labels: str | None = None
depends_on: str | None = None

_SOURCES_WITH_IMPORT = (
    "'serper', 'company_site', 'linkedin_proxycurl', 'social_profiles', 'csv_import'"
)
_SOURCES_WITHOUT_IMPORT = (
    "'serper', 'company_site', 'linkedin_proxycurl', 'social_profiles'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE lead DROP CONSTRAINT IF EXISTS ck_lead_source")
    op.execute(
        "ALTER TABLE lead ADD CONSTRAINT ck_lead_source "
        f"CHECK (source IN ({_SOURCES_WITH_IMPORT}))"
    )


def downgrade() -> None:
    # Imported rows would violate the narrower constraint, so drop them first.
    # They cannot be re-derived, but leaving the migration un-reversible is
    # worse than a documented, deliberate deletion.
    op.execute("DELETE FROM lead WHERE source = 'csv_import'")
    op.execute("ALTER TABLE lead DROP CONSTRAINT IF EXISTS ck_lead_source")
    op.execute(
        "ALTER TABLE lead ADD CONSTRAINT ck_lead_source "
        f"CHECK (source IN ({_SOURCES_WITHOUT_IMPORT}))"
    )
