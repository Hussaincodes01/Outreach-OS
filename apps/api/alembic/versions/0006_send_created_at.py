"""Phase 4 — add created_at to send (parity with other audit tables).

Without this, the SendOut schema (which extends IdTimestampMixin) raises
AttributeError when serialised by /v1/sends.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006_send_created_at"
down_revision: str | None = "0005_phase4_send"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "send",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("send", "created_at")
