"""Auth schemas."""
from __future__ import annotations

import uuid

from outreach_os.domain.schemas.common import ApiModel


class AuthContext(ApiModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
