"""User model — under RLS via tenant_id."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from outreach_os.core.db import Base


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # NULL until the user clicks the verification link. Not enforced at login —
    # locking people out of a workspace they are already paying for, because a
    # verification email landed in spam, loses customers.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # 'password' | 'google' | 'microsoft'. SSO users still carry an (unusable)
    # password_hash so no code path can treat a missing hash as a match.
    auth_provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="password"
    )
    # The provider's stable subject id. Matched on instead of email, because
    # an address can be reassigned to a different person inside a company.
    auth_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Platform staff, NOT a tenant role. `role` describes a user's position
    # inside their own workspace; this grants read access across customers and
    # is set only by direct database statement (see migration 0018).
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_app_user_role"),
        Index("ix_app_user_tenant", "tenant_id"),
        Index("uq_app_user_tenant_email", "tenant_id", "email", unique=True),
    )
