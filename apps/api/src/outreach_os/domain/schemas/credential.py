"""Credential schemas — the secret payload never round-trips back to the client."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel


class CredentialCreate(ApiModel):
    kind: str = Field(
        min_length=1,
        max_length=64,
        description="Credential kind, e.g. llm_openai, llm_anthropic, serper, proxycurl.",
    )
    label: str = Field(min_length=1, max_length=200)
    secret_payload: dict[str, Any] = Field(
        description="Arbitrary JSON-serialisable secret material. Encrypted on the way in.",
    )


class CredentialOut(ApiModel):
    id: uuid.UUID
    kind: str
    label: str
    created_at: datetime
    last_used_at: datetime | None = None
    has_secret: bool = True


class CredentialTestResult(ApiModel):
    ok: bool
    message: str = ""
