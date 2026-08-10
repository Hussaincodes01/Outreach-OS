"""Multi-provider catalogue: routing, capabilities, and embedding constraints.

The catalogue is a suggestion list, not a whitelist — the guarantee we need is
that provider routing stays correct as it grows, that capability flags actually
change behaviour, and that we never offer an embedding model the vector column
cannot store.
"""
from __future__ import annotations

import pytest

from outreach_os.domain.models.knowledge_base_chunk import EMBEDDING_DIM
from outreach_os.services.llm_credentials import (
    PROVIDERS,
    VALID_CREDENTIAL_KINDS,
    chat_models,
    embedding_models,
    embedding_spec,
    model_spec,
    provider_for_model,
    supports_tools,
)
from tests.conftest import bearer, signup, unique_email

# --- catalogue integrity ----------------------------------------------------


def test_every_catalogue_model_routes_to_its_own_provider() -> None:
    """A model filed under the wrong provider would spend the wrong key."""
    for provider in PROVIDERS:
        for model in provider.models:
            assert provider_for_model(model.id) == provider.provider, model.id
        for emb in provider.embedding_models:
            assert provider_for_model(emb.id) == provider.provider, emb.id


def test_verify_model_belongs_to_its_provider() -> None:
    for provider in PROVIDERS:
        assert provider_for_model(provider.verify_model) == provider.provider


def test_provider_identifiers_are_unique() -> None:
    assert len({p.provider for p in PROVIDERS}) == len(PROVIDERS)
    assert len({p.credential_kind for p in PROVIDERS}) == len(PROVIDERS)


def test_model_ids_are_unique() -> None:
    ids = [m.id for m in chat_models()]
    assert len(set(ids)) == len(ids)


def test_every_provider_kind_is_an_accepted_credential_kind() -> None:
    for provider in PROVIDERS:
        assert provider.credential_kind in VALID_CREDENTIAL_KINDS


def test_catalogue_covers_several_providers() -> None:
    """Guards against a refactor silently collapsing the catalogue."""
    assert len(PROVIDERS) >= 10
    assert len(chat_models()) >= 25


# --- embedding constraint ---------------------------------------------------


def test_every_offered_embedding_model_matches_the_vector_column() -> None:
    """`knowledge_base_chunk.embedding` is a fixed-width column; a mismatched
    model would fail at insert time, long after the user chose it."""
    offered = embedding_models()
    assert offered, "at least one embedding model must be selectable"
    for emb in offered:
        assert emb.dimensions == EMBEDDING_DIM, emb.id


def test_large_embedding_model_is_marked_for_dimension_override() -> None:
    """text-embedding-3-large is natively 3072; it only fits because we ask
    the provider to project it down."""
    spec = embedding_spec("openai/text-embedding-3-large")
    assert spec is not None
    assert spec.supports_dimension_override is True
    assert spec.dimensions == EMBEDDING_DIM


# --- capability flags -------------------------------------------------------


def test_models_without_function_calling_are_flagged() -> None:
    """Perplexity's Sonar has no tool calling. The agent must know that up
    front rather than discovering it through a failed request."""
    assert supports_tools("perplexity/sonar") is False
    assert supports_tools("deepseek/deepseek-reasoner") is False


def test_mainstream_models_support_tools() -> None:
    assert supports_tools("openai/gpt-4o-mini") is True
    assert supports_tools("anthropic/claude-sonnet-4-20250514") is True


def test_unknown_models_are_assumed_capable() -> None:
    """Optimism costs one failed call that the agent already recovers from;
    pessimism would disable the agent for every newly released model."""
    assert model_spec("openai/some-model-released-tomorrow") is None
    assert supports_tools("openai/some-model-released-tomorrow") is True


# --- self-hosted providers --------------------------------------------------


def test_self_hosted_provider_needs_a_base_url_but_no_key() -> None:
    ollama = next(p for p in PROVIDERS if p.provider == "ollama")
    assert ollama.requires_api_base is True
    assert ollama.requires_api_key is False
    assert ollama.api_base_hint


# --- API surface ------------------------------------------------------------

pytestmark_async = pytest.mark.asyncio


@pytest.mark.asyncio
async def test_providers_endpoint_lists_the_whole_catalogue(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Catalogue",
    )
    resp = await client.get(
        "/v1/credentials/providers", headers=bearer(a["access_token"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(PROVIDERS)
    by_provider = {p["provider"]: p for p in body}
    # A few that must be reachable from the UI.
    for name in ("openai", "anthropic", "deepseek", "openrouter", "ollama"):
        assert name in by_provider, name
    assert by_provider["ollama"]["requires_api_key"] is False
    assert by_provider["ollama"]["api_base_hint"]
    assert by_provider["openai"]["model_count"] > 0


@pytest.mark.asyncio
async def test_llm_settings_reports_availability_per_model(client) -> None:
    """Models are listed even when unavailable, so the picker can show what
    connecting another provider would unlock."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Avail",
    )
    headers = bearer(a["access_token"])

    before = (await client.get("/v1/onboarding/llm-settings", headers=headers)).json()
    assert len(before["models"]) >= 25
    assert all(m["available"] is False for m in before["models"])

    await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_deepseek",
            "label": "ds",
            "secret_payload": {"api_key": "sk-ds-test"},
        },
        headers=headers,
    )
    after = (await client.get("/v1/onboarding/llm-settings", headers=headers)).json()
    by_id = {m["id"]: m for m in after["models"]}
    assert by_id["deepseek/deepseek-chat"]["available"] is True
    assert by_id["openai/gpt-4o-mini"]["available"] is False
    # Capability metadata reaches the UI.
    assert by_id["deepseek/deepseek-reasoner"]["supports_tools"] is False


@pytest.mark.asyncio
async def test_embedding_model_requires_its_own_provider_key(client) -> None:
    """Drafting on DeepSeek does not entitle you to OpenAI embeddings."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Emb",
    )
    headers = bearer(a["access_token"])
    await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_deepseek",
            "label": "ds",
            "secret_payload": {"api_key": "sk-ds-test"},
        },
        headers=headers,
    )
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={
            "default_llm_model": "deepseek/deepseek-chat",
            "embedding_llm_model": "openai/text-embedding-3-small",
        },
        headers=headers,
    )
    assert resp.status_code == 428, resp.text
    assert "openai" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_draft_and_embed_can_use_different_providers(client) -> None:
    """The point of a separate embedding setting: an Anthropic-only workspace
    could not otherwise use the knowledge base at all."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Split",
    )
    headers = bearer(a["access_token"])
    for kind in ("llm_anthropic", "llm_openai"):
        await client.post(
            "/v1/credentials",
            json={"kind": kind, "label": kind, "secret_payload": {"api_key": "sk-test"}},
            headers=headers,
        )
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={
            "default_llm_model": "anthropic/claude-sonnet-4-20250514",
            "embedding_llm_model": "openai/text-embedding-3-small",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_llm_model"] == "anthropic/claude-sonnet-4-20250514"
    assert body["embedding_llm_model"] == "openai/text-embedding-3-small"


@pytest.mark.asyncio
async def test_non_1536_embedding_model_is_rejected(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="BadEmb",
    )
    headers = bearer(a["access_token"])
    await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_mistral",
            "label": "m",
            "secret_payload": {"api_key": "sk-test"},
        },
        headers=headers,
    )
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={
            "default_llm_model": None,
            "embedding_llm_model": "mistral/mistral-embed",
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert str(EMBEDDING_DIM) in resp.json()["detail"]


@pytest.mark.asyncio
async def test_omitted_setting_is_left_alone_not_reset(client) -> None:
    """PUT used to assign both fields unconditionally, so a client sending only
    the chat model silently cleared the embedding model — changing how future
    chunks embed and stranding existing vectors."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Partial",
    )
    headers = bearer(a["access_token"])
    for kind in ("llm_openai", "llm_deepseek"):
        await client.post(
            "/v1/credentials",
            json={"kind": kind, "label": kind, "secret_payload": {"api_key": "sk-t"}},
            headers=headers,
        )
    await client.put(
        "/v1/onboarding/llm-settings",
        json={
            "default_llm_model": "openai/gpt-4o-mini",
            "embedding_llm_model": "openai/text-embedding-3-small",
        },
        headers=headers,
    )
    # Send ONLY the chat model.
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={"default_llm_model": "deepseek/deepseek-chat"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_llm_model"] == "deepseek/deepseek-chat"
    assert body["embedding_llm_model"] == "openai/text-embedding-3-small"


@pytest.mark.asyncio
async def test_explicit_null_still_resets(client) -> None:
    """"Leave alone" must not make it impossible to clear a setting."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Reset",
    )
    headers = bearer(a["access_token"])
    await client.post(
        "/v1/credentials",
        json={"kind": "llm_openai", "label": "o", "secret_payload": {"api_key": "sk-t"}},
        headers=headers,
    )
    await client.put(
        "/v1/onboarding/llm-settings",
        json={"default_llm_model": "openai/gpt-4o-mini"},
        headers=headers,
    )
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={"default_llm_model": None},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_llm_model"] is None


@pytest.mark.asyncio
async def test_credential_saved_under_token_is_usable(client) -> None:
    """The create endpoint accepts `token`; the resolver must read it too, or
    the workspace shows "connected" while every draft fails."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="TokenField",
    )
    headers = bearer(a["access_token"])
    resp = await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_openai",
            "label": "via token",
            "secret_payload": {"token": "sk-stored-under-token"},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    # Selecting a model requires load_credentials() to find a usable key.
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={"default_llm_model": "openai/gpt-4o-mini"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_self_hosted_provider_rejects_a_missing_base_url(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Local",
    )
    resp = await client.post(
        "/v1/credentials",
        json={"kind": "llm_ollama", "label": "local", "secret_payload": {}},
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 422, resp.text
    assert "api_base" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_self_hosted_provider_connects_with_only_a_base_url(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Local2",
    )
    headers = bearer(a["access_token"])
    resp = await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_ollama",
            "label": "local",
            "secret_payload": {"api_base": "http://localhost:11434"},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    settings = (await client.get("/v1/onboarding/llm-settings", headers=headers)).json()
    by_id = {m["id"]: m for m in settings["models"]}
    assert by_id["ollama/llama3.1"]["available"] is True
