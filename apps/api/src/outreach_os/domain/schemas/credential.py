"""Credential schemas — the secret payload never round-trips back to the client."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

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
    # True when the model list can't be enumerated ahead of time (a gateway or
    # self-hosted endpoint), so the UI must accept a typed model name.
    allows_custom_model: bool = False
    # Env var names the operator can set in `.env` to connect this provider
    # without going through the UI at all.
    env_var: str
    env_base_var: str
    # None when not connected. "env" beats "stored" — see services.llm_credentials.
    configured_via: Literal["env", "stored"] | None = None


class ProviderTestOut(ApiModel):
    """Result of POST /credentials/providers/{provider}/test."""

    ok: bool
    message: str = ""


class ScrapingKeyOut(ApiModel):
    """One non-LLM integration (Serper, Proxycurl, ...) and whether its env
    var is set. These have no stored-credential equivalent surfaced here —
    GET /credentials lists any stored row separately."""

    kind: str
    env_var: str
    configured: bool


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
