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


class UserInvite(ApiModel):
    email: EmailStr
    role: str = Field(default="member", pattern="^(owner|admin|member)$")
    password: str = Field(min_length=12, max_length=128)
