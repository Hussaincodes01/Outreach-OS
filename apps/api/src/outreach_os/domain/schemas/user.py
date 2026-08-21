"""User schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from outreach_os.domain.schemas.common import ApiModel


class UserOut(ApiModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime
    # NULL until confirmed. Surfaced so the app can prompt without a second
    # round-trip; access is never gated on it.
    email_verified_at: datetime | None = None
    # Lets the app show the admin console link. Read-only: no endpoint sets it.
    is_platform_admin: bool = False


class UserInvite(ApiModel):
    email: EmailStr
    role: str = Field(default="member", pattern="^(owner|admin|member)$")
    password: str = Field(min_length=12, max_length=128)
