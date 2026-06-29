"""Common base for Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class IdTimestampMixin(ApiModel):
    id: uuid.UUID
    created_at: datetime
