"""Audit schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel


class AuditEventOut(ApiModel):
    id: uuid.UUID
    actor_kind: str
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    payload: dict[str, Any]
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


class AuditPage(ApiModel):
    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int


class AuditQuery(ApiModel):
    action: str | None = None
    actor_kind: str | None = Field(default=None, pattern="^(user|system|agent)$")
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
