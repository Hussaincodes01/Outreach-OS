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


class ProviderOut(ApiModel):
    """A connectable LLM provider, plus whether this tenant has wired it up.

    Drives the integrations page and the onboarding checklist, so the UI never
    hard-codes a provider list that can drift from the backend.
    """

    provider: str
    credential_kind: str
    label: str
    console_url: str
    supports_embeddings: bool
    connected: bool
    # Populated only after a successful "Test" — we never probe on list.
    last_verified_at: datetime | None = None
    description: str = ""
    # Self-hosted / gateway providers take a base URL; some take no key at all.
    requires_api_base: bool = False
    requires_api_key: bool = True
    api_base_hint: str | None = None
    model_count: int = 0


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
    # True when the check actually reached the provider (rather than only
    # confirming we could decrypt the stored blob).
    verified_live: bool = False
