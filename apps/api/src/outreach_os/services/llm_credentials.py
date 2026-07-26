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
class ModelSpec:
    """A suggested chat model.

    The catalogue is a UX affordance, NOT a whitelist: `provider_for_model`
    validates the provider prefix only, so a tenant can use a model the day it
    ships without waiting for us to add it here.
    """

    id: str
    label: str
    # Function calling. False disables the agentic research loop for this model
    # (we skip straight to deterministic research rather than failing a call).
    supports_tools: bool = True
    context_window: int = 128_000
    # "fast" (cheap, high volume) | "balanced" | "frontier" (best quality)
    tier: str = "balanced"


@dataclass(frozen=True)
class EmbeddingModelSpec:
    """An embedding model that fits the knowledge-base vector column.

    `knowledge_base_chunk.embedding` is `Vector(1536)`, so only models that
    produce exactly 1536 dimensions — natively, or via an API-side
    `dimensions` override — can be offered. Anything else would be rejected at
    insert time.
    """

    id: str
    label: str
    dimensions: int
    # Provider accepts a `dimensions` argument to project down (OpenAI v3).
    supports_dimension_override: bool = False


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
    models: tuple[ModelSpec, ...] = ()
    embedding_models: tuple[EmbeddingModelSpec, ...] = ()
    # Self-hosted / gateway providers need a base URL instead of (or as well
    # as) a key.
    requires_api_base: bool = False
    requires_api_key: bool = True
    api_base_hint: str | None = None
    description: str = ""

    @property
    def supports_embeddings(self) -> bool:
        return bool(self.embedding_models)


# The single source of truth for "which providers can a tenant connect?".
# The web integrations page reads this via /v1/credentials/providers, so the
# two cannot drift.
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        provider="openai",
        credential_kind="llm_openai",
        label="OpenAI",
        console_url="https://platform.openai.com/api-keys",
        verify_model="openai/gpt-4o-mini",
        description="Broadest model range. The only provider that can also power the knowledge base.",
        models=(
            ModelSpec("openai/gpt-4o-mini", "GPT-4o mini", tier="fast"),
            ModelSpec("openai/gpt-4o", "GPT-4o", tier="balanced"),
            ModelSpec("openai/gpt-4.1", "GPT-4.1", context_window=1_000_000),
            ModelSpec("openai/gpt-4.1-mini", "GPT-4.1 mini", context_window=1_000_000, tier="fast"),
            ModelSpec("openai/o4-mini", "o4-mini (reasoning)", tier="frontier"),
        ),
        embedding_models=(
            EmbeddingModelSpec(
                "openai/text-embedding-3-small", "text-embedding-3-small", 1536
            ),
            EmbeddingModelSpec(
                "openai/text-embedding-3-large",
                "text-embedding-3-large (projected to 1536)",
                1536,
                supports_dimension_override=True,
            ),
            EmbeddingModelSpec(
                "openai/text-embedding-ada-002", "text-embedding-ada-002 (legacy)", 1536
            ),
        ),
    ),
    ProviderSpec(
        provider="anthropic",
        credential_kind="llm_anthropic",
        label="Anthropic",
        console_url="https://console.anthropic.com/settings/keys",
        verify_model="anthropic/claude-3-5-haiku-20241022",
        description="Strong long-form writing. No embeddings API — pair with OpenAI for the knowledge base.",
        models=(
            ModelSpec(
                "anthropic/claude-3-5-haiku-20241022",
                "Claude 3.5 Haiku",
                context_window=200_000,
                tier="fast",
            ),
            ModelSpec(
                "anthropic/claude-sonnet-4-20250514",
                "Claude Sonnet 4",
                context_window=200_000,
            ),
            ModelSpec(
                "anthropic/claude-opus-4-20250514",
                "Claude Opus 4",
                context_window=200_000,
                tier="frontier",
            ),
        ),
    ),
    ProviderSpec(
        provider="gemini",
        credential_kind="llm_gemini",
        label="Google Gemini",
        console_url="https://aistudio.google.com/app/apikey",
        verify_model="gemini/gemini-2.0-flash",
        description="Very large context windows and a generous free tier.",
        models=(
            ModelSpec("gemini/gemini-2.0-flash", "Gemini 2.0 Flash", context_window=1_000_000, tier="fast"),
            ModelSpec("gemini/gemini-2.5-flash", "Gemini 2.5 Flash", context_window=1_000_000, tier="fast"),
            ModelSpec("gemini/gemini-2.5-pro", "Gemini 2.5 Pro", context_window=2_000_000, tier="frontier"),
        ),
    ),
    ProviderSpec(
        provider="groq",
        credential_kind="llm_groq",
        label="Groq",
        console_url="https://console.groq.com/keys",
        verify_model="groq/llama-3.1-8b-instant",
        description="Fastest inference for open models. Good for high-volume drafting.",
        models=(
            ModelSpec("groq/llama-3.1-8b-instant", "Llama 3.1 8B", context_window=131_072, tier="fast"),
            ModelSpec("groq/llama-3.3-70b-versatile", "Llama 3.3 70B", context_window=131_072),
            ModelSpec("groq/moonshotai/kimi-k2-instruct", "Kimi K2", context_window=131_072),
        ),
    ),
    ProviderSpec(
        provider="mistral",
        credential_kind="llm_mistral",
        label="Mistral",
        console_url="https://console.mistral.ai/api-keys",
        verify_model="mistral/mistral-small-latest",
        description="EU-hosted, strong multilingual output.",
        models=(
            ModelSpec("mistral/mistral-small-latest", "Mistral Small", tier="fast"),
            ModelSpec("mistral/mistral-medium-latest", "Mistral Medium"),
            ModelSpec("mistral/mistral-large-latest", "Mistral Large", tier="frontier"),
        ),
    ),
    ProviderSpec(
        provider="deepseek",
        credential_kind="llm_deepseek",
        label="DeepSeek",
        console_url="https://platform.deepseek.com/api_keys",
        verify_model="deepseek/deepseek-chat",
        description="Very low cost per token. Popular for bulk generation.",
        models=(
            ModelSpec("deepseek/deepseek-chat", "DeepSeek Chat", context_window=64_000, tier="fast"),
            ModelSpec(
                "deepseek/deepseek-reasoner",
                "DeepSeek Reasoner",
                context_window=64_000,
                supports_tools=False,
                tier="frontier",
            ),
        ),
    ),
    ProviderSpec(
        provider="xai",
        credential_kind="llm_xai",
        label="xAI (Grok)",
        console_url="https://console.x.ai",
        verify_model="xai/grok-3-mini",
        description="Grok models with large context.",
        models=(
            ModelSpec("xai/grok-3-mini", "Grok 3 mini", context_window=131_072, tier="fast"),
            ModelSpec("xai/grok-3", "Grok 3", context_window=131_072),
            ModelSpec("xai/grok-4", "Grok 4", context_window=256_000, tier="frontier"),
        ),
    ),
    ProviderSpec(
        provider="cohere",
        credential_kind="llm_cohere",
        label="Cohere",
        console_url="https://dashboard.cohere.com/api-keys",
        verify_model="cohere/command-r",
        description="Command models tuned for business writing and RAG.",
        models=(
            ModelSpec("cohere/command-r", "Command R", tier="fast"),
            ModelSpec("cohere/command-r-plus", "Command R+", tier="frontier"),
            ModelSpec("cohere/command-a-03-2025", "Command A", context_window=256_000),
        ),
    ),
    ProviderSpec(
        provider="together_ai",
        credential_kind="llm_together",
        label="Together AI",
        console_url="https://api.together.xyz/settings/api-keys",
        verify_model="together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        description="Hosted open-weight models (Llama, Qwen, DeepSeek) at low cost.",
        models=(
            ModelSpec(
                "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "Llama 3.3 70B Turbo",
                context_window=131_072,
            ),
            ModelSpec(
                "together_ai/Qwen/Qwen2.5-72B-Instruct-Turbo",
                "Qwen 2.5 72B Turbo",
                context_window=32_768,
            ),
        ),
    ),
    ProviderSpec(
        provider="fireworks_ai",
        credential_kind="llm_fireworks",
        label="Fireworks AI",
        console_url="https://fireworks.ai/account/api-keys",
        verify_model="fireworks_ai/accounts/fireworks/models/llama-v3p3-70b-instruct",
        description="Fast hosted open models with function calling.",
        models=(
            ModelSpec(
                "fireworks_ai/accounts/fireworks/models/llama-v3p3-70b-instruct",
                "Llama 3.3 70B",
                context_window=131_072,
            ),
            ModelSpec(
                "fireworks_ai/accounts/fireworks/models/qwen3-235b-a22b",
                "Qwen 3 235B",
                context_window=128_000,
                tier="frontier",
            ),
        ),
    ),
    ProviderSpec(
        provider="openrouter",
        credential_kind="llm_openrouter",
        label="OpenRouter",
        console_url="https://openrouter.ai/keys",
        verify_model="openrouter/openai/gpt-4o-mini",
        description=(
            "One key, hundreds of models across providers. Use any "
            "'openrouter/<vendor>/<model>' id — the list below is a starting point."
        ),
        models=(
            ModelSpec("openrouter/openai/gpt-4o-mini", "GPT-4o mini (via OpenRouter)", tier="fast"),
            ModelSpec(
                "openrouter/anthropic/claude-sonnet-4",
                "Claude Sonnet 4 (via OpenRouter)",
                context_window=200_000,
            ),
            ModelSpec(
                "openrouter/meta-llama/llama-3.3-70b-instruct",
                "Llama 3.3 70B (via OpenRouter)",
                context_window=131_072,
            ),
        ),
    ),
    ProviderSpec(
        provider="perplexity",
        credential_kind="llm_perplexity",
        label="Perplexity",
        console_url="https://www.perplexity.ai/settings/api",
        verify_model="perplexity/sonar",
        description=(
            "Answers are grounded in live web search. No function calling, so "
            "the agent uses deterministic research with this provider."
        ),
        models=(
            ModelSpec("perplexity/sonar", "Sonar", supports_tools=False, tier="fast"),
            ModelSpec("perplexity/sonar-pro", "Sonar Pro", supports_tools=False),
        ),
    ),
    ProviderSpec(
        provider="ollama",
        credential_kind="llm_ollama",
        label="Ollama (self-hosted)",
        console_url="https://ollama.com/library",
        verify_model="ollama/llama3.1",
        description=(
            "Run models on your own hardware. Nothing leaves your network. "
            "Point this at your Ollama server URL; no API key required."
        ),
        requires_api_base=True,
        requires_api_key=False,
        api_base_hint="http://localhost:11434",
        models=(
            ModelSpec("ollama/llama3.1", "Llama 3.1 (local)", context_window=131_072),
            ModelSpec("ollama/qwen2.5", "Qwen 2.5 (local)", context_window=32_768),
            ModelSpec(
                "ollama/mistral", "Mistral (local)", context_window=32_768, tier="fast"
            ),
        ),
    ),
)

_BY_PROVIDER = {p.provider: p for p in PROVIDERS}
_BY_KIND = {p.credential_kind: p for p in PROVIDERS}
_MODELS_BY_ID = {m.id: m for p in PROVIDERS for m in p.models}
_EMBEDDINGS_BY_ID = {e.id: e for p in PROVIDERS for e in p.embedding_models}


def provider_spec(provider: str) -> ProviderSpec | None:
    return _BY_PROVIDER.get(provider)


def spec_for_kind(kind: str) -> ProviderSpec | None:
    return _BY_KIND.get(kind)


def model_spec(model: str) -> ModelSpec | None:
    """Catalogue entry for a model, or None if it's one we don't know.

    Unknown is fine and expected — the catalogue is a suggestion list, not a
    whitelist, so tenants can use newly released models immediately.
    """
    return _MODELS_BY_ID.get(model)


def embedding_spec(model: str) -> EmbeddingModelSpec | None:
    return _EMBEDDINGS_BY_ID.get(model)


def supports_tools(model: str) -> bool:
    """Whether to attempt the agentic tool-calling loop for this model.

    Unknown models are assumed capable: the agent degrades gracefully on a
    tool-calling error, so optimism costs one failed call, whereas pessimism
    would silently disable the agent for every new model.
    """
    spec = model_spec(model)
    return spec.supports_tools if spec else True


def chat_models() -> tuple[ModelSpec, ...]:
    return tuple(m for p in PROVIDERS for m in p.models)


def embedding_models() -> tuple[EmbeddingModelSpec, ...]:
    return tuple(e for p in PROVIDERS for e in p.embedding_models)

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
    api_base = str(payload.get("api_base") or "").strip() or spec.api_base_hint

    if spec.requires_api_key and not api_key:
        return None
    if spec.requires_api_base and not api_base:
        return None
    if not spec.requires_api_key and not api_key:
        # Self-hosted servers (Ollama) take no key, but LiteLLM still wants a
        # non-empty value on the field.
        api_key = "not-required"

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
    "EmbeddingModelSpec",
    "MissingLLMCredentialsError",
    "ModelSpec",
    "ProviderSpec",
    "UnknownProviderError",
    "chat_models",
    "client_for",
    "embedding_models",
    "embedding_spec",
    "load_credentials",
    "model_spec",
    "provider_for_model",
    "provider_spec",
    "resolve_llm_client",
    "spec_for_kind",
    "supports_tools",
    "verify_credentials",
]
