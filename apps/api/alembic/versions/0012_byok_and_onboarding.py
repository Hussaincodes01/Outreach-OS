"""BYOK + self-serve onboarding.

- credential.last_verified_at: set when a live provider call succeeded with
  the stored key. Decrypting a blob proves nothing about whether the provider
  will accept it, so the two are tracked separately.
- tenant.default_llm_model: the LiteLLM `provider/model` this tenant drafts
  with. The provider prefix selects which of the tenant's own keys is used.
- tenant.onboarding_state / onboarding_completed_at: drives the first-run
  checklist. JSONB so adding a step needs no migration.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012_byok_and_onboarding"
down_revision: str | None = "0011_add_social_profiles_source"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "credential",
        sa.Column("last_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant",
        sa.Column("default_llm_model", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenant",
        sa.Column(
            "onboarding_state",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "tenant",
        sa.Column(
            "onboarding_completed_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant", "onboarding_completed_at")
    op.drop_column("tenant", "onboarding_state")
    op.drop_column("tenant", "default_llm_model")
    op.drop_column("credential", "last_verified_at")
