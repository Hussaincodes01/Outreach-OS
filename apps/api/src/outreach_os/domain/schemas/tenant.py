"""Tenant schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel


class TenantOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    status: str
    plan: str
    created_at: datetime
    updated_at: datetime


class TenantUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
