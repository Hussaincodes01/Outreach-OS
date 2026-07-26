"""Resolve a tenant's own LLM credentials (BYOK) into a usable client.

Strict BYOK: there is no server-side fallback key and no silent fake. If the
tenant has not connected a key for the provider their model needs, we raise
`MissingLLMCredentialsError`, which the API layer turns into an actionable
message pointing at the integrations page. A tenant is never billed to, or
rate-limited by, another tenant's key.

Model names are LiteLLM-style `provider/model` (e.g. `openai/gpt-4o-mini`).
The provider prefix selects which credential kind to look up.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.errors import SetupRequiredError, ValidationError
from outreach_os.core.llm import (
    LiteLLMClient,
    LLMAuthError,
    LLMClient,
    LLMCredentials,
    LLMError,
    get_llm_client,
    redact,
)
from outreach_os.domain.models.credential import Credential
from outreach_os.services import vault_service

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSpec:
    """A provider the tenant can connect a key for."""

    provider: str
    credential_kind: str
    label: str
    # Shown in the UI so a user knows where to get the key.
    console_url: str
    # A cheap model used to verify the key actually works.
    verify_model: str
    supports_embeddings: bool = False


# The single source of truth for "which providers can a tenant connect?".
# The web integrations page reads this via /v1/integrations/providers, so the
# two cannot drift.
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        provider="openai",
        credential_kind="llm_openai",
        label="OpenAI",
        console_url="https://platform.openai.com/api-keys",
        verify_model="openai/gpt-4o-mini",
        supports_embeddings=True,
    ),
    ProviderSpec(
        provider="anthropic",
        credential_kind="llm_anthropic",
        label="Anthropic",
        console_url="https://console.anthropic.com/settings/keys",
        verify_model="anthropic/claude-3-5-haiku-20241022",
    ),
    ProviderSpec(
        provider="gemini",
        credential_kind="llm_gemini",
        label="Google Gemini",
        console_url="https://aistudio.google.com/app/apikey",
        verify_model="gemini/gemini-2.0-flash",
    ),
    ProviderSpec(
        provider="groq",
        credential_kind="llm_groq",
        label="Groq",
        console_url="https://console.groq.com/keys",
        verify_model="groq/llama-3.1-8b-instant",
    ),
    ProviderSpec(
        provider="mistral",
        credential_kind="llm_mistral",
        label="Mistral",
        console_url="https://console.mistral.ai/api-keys",
        verify_model="mistral/mistral-small-latest",
        supports_embeddings=True,
    ),
)

_BY_PROVIDER = {p.provider: p for p in PROVIDERS}
_BY_KIND = {p.credential_kind: p for p in PROVIDERS}

# Non-LLM integrations, kept here so credential `kind` is validated in one place.
NON_LLM_KINDS: tuple[str, ...] = ("serper", "proxycurl", "rapidapi", "scrapingbee")

VALID_CREDENTIAL_KINDS: tuple[str, ...] = tuple(_BY_KIND) + NON_LLM_KINDS


class MissingLLMCredentialsError(SetupRequiredError):
    """The tenant has not connected a key for the provider they're using."""

    def __init__(self, provider: str) -> None:
        spec = _BY_PROVIDER.get(provider)
        label = spec.label if spec else provider
        super().__init__(
            f"No {label} API key connected. Add one under Settings → Integrations "
            f"to start generating drafts."
        )
        self.provider = provider


class UnknownProviderError(ValidationError):
    """The configured model names a provider we don't support."""


def provider_for_model(model: str) -> str:
    """Extract the LiteLLM provider prefix from a model name.

    `openai/gpt-4o-mini` -> `openai`. A bare name (no slash) is ambiguous and
    would otherwise silently fall through to whatever LiteLLM guesses, so it is
    rejected rather than defaulted.
    """
    provider, _, rest = model.partition("/")
    if not rest:
        raise UnknownProviderError(
            f"model {model!r} must be provider-qualified, e.g. 'openai/{model}'"
        )
    if provider not in _BY_PROVIDER:
        supported = ", ".join(sorted(_BY_PROVIDER))
        raise UnknownProviderError(
            f"unsupported provider {provider!r} in model {model!r}; supported: {supported}"
        )
    return provider


async def load_credentials(
    session: AsyncSession, *, tenant_id: uuid.UUID, provider: str
) -> LLMCredentials | None:
    """Decrypt the tenant's key for one provider, or None if not connected.

    The session MUST already have the RLS GUC bound to `tenant_id` — the
    credential table is RLS-protected.
    """
    spec = _BY_PROVIDER.get(provider)
    if spec is None:
        raise UnknownProviderError(f"unsupported provider {provider!r}")

    cred = (
        await session.execute(
            select(Credential)
            .where(
                Credential.tenant_id == tenant_id,
                Credential.kind == spec.credential_kind,
            )
            .order_by(Credential.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if cred is None:
        return None

    try:
        payload = vault_service.decrypt_for_tenant(str(tenant_id), cred.ciphertext)
    except Exception:
        # Never log the ciphertext or the tenant's key material.
        log.warning(
            "llm_credential_decrypt_failed",
            extra={"credential_id": str(cred.id), "kind": cred.kind},
        )
        return None

    api_key = str(payload.get("api_key") or payload.get("key") or "").strip()
    if not api_key:
        return None
    api_base = str(payload.get("api_base") or "").strip() or None
    return LLMCredentials(provider=provider, api_key=api_key, api_base=api_base)


async def resolve_llm_client(
    session: AsyncSession, *, tenant_id: uuid.UUID, model: str
) -> LLMClient:
    """Return a client bound to this tenant's key for `model`'s provider.

    An injected override (the test fake) always wins, so the suite never needs
    real credentials. Otherwise this is strict BYOK.
    """
    override = get_llm_client()
    if override is not None:
        return override

    provider = provider_for_model(model)
    creds = await load_credentials(session, tenant_id=tenant_id, provider=provider)
    if creds is None:
        raise MissingLLMCredentialsError(provider)
    return LiteLLMClient(creds)


async def client_for(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    model: str,
    injected: LLMClient | None = None,
) -> LLMClient:
    """Call-site helper: prefer an explicitly injected client, else resolve.

    Services keep an optional `llm=` constructor argument so tests can pass a
    deterministic fake; everything else goes through tenant BYOK resolution.
    """
    if injected is not None:
        return injected
    return await resolve_llm_client(session, tenant_id=tenant_id, model=model)


async def verify_credentials(
    session: AsyncSession, *, tenant_id: uuid.UUID, provider: str
) -> tuple[bool, str]:
    """Make one cheap real call to prove the key works.

    Returns (ok, message). Used by the "Test" button and the onboarding
    checklist — decrypting successfully says nothing about whether the
    provider will accept the key, which is what a user actually wants to know.
    """
    spec = _BY_PROVIDER.get(provider)
    if spec is None:
        return False, f"unsupported provider {provider!r}"

    creds = await load_credentials(session, tenant_id=tenant_id, provider=provider)
    if creds is None:
        return False, "no API key stored for this provider"

    client = LiteLLMClient(creds)
    try:
        # 1 token is enough to exercise auth without a meaningful bill.
        await _achat_probe(client, spec.verify_model)
    except LLMAuthError as exc:
        return False, redact(str(exc))
    except LLMError as exc:
        # Reachable but unhappy (quota, model not enabled for this account).
        return False, redact(str(exc))
    return True, f"{spec.label} key verified"


async def _achat_probe(client: LiteLLMClient, model: str) -> None:
    import asyncio

    await asyncio.to_thread(
        client.chat,
        model,
        [{"role": "user", "content": "ping"}],
        max_tokens=1,
        temperature=0.0,
        timeout=20,
    )


__all__ = [
    "NON_LLM_KINDS",
    "PROVIDERS",
    "VALID_CREDENTIAL_KINDS",
    "MissingLLMCredentialsError",
    "ProviderSpec",
    "UnknownProviderError",
    "client_for",
    "load_credentials",
    "provider_for_model",
    "resolve_llm_client",
    "verify_credentials",
]
