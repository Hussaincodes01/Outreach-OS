"""BYOK: per-tenant LLM credential resolution.

The properties that matter for a bring-your-own-key product:

1. A tenant's key is resolved from their own encrypted vault unless the
   operator has set it in the environment / `.env` instead — this is a
   single-user build, so the env key and the one workspace's key are the
   same thing, and env wins when both are present (see `core.env_keys`).
2. Tenant A's stored key is never visible to tenant B.
3. With no key connected anywhere, drafting fails with an actionable setup
   error rather than silently producing fabricated output.
4. Provider selection follows the model name.
"""
from __future__ import annotations

import uuid

import pytest

from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import LiteLLMClient, LLMCredentials, set_llm_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.tenant import Tenant
from outreach_os.services.credential_lookup import create_credential
from outreach_os.services.llm_credentials import (
    MissingLLMCredentialsError,
    UnknownProviderError,
    load_credentials,
    provider_for_model,
    resolve_llm_client,
)

pytestmark = pytest.mark.asyncio


async def _mk_tenant(slug_prefix: str) -> uuid.UUID:
    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    async with factory() as session, session.begin():
        session.add(
            Tenant(
                id=tenant_id,
                slug=f"{slug_prefix}-{tenant_id.hex[:8]}",
                name=slug_prefix,
                status="active",
                plan="starter",
            )
        )
    return tenant_id


async def _store_key(tenant_id: uuid.UUID, kind: str, api_key: str) -> None:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        await create_credential(
            session, tenant_id=tenant_id, kind=kind, plaintext={"api_key": api_key}
        )


# --- provider routing -------------------------------------------------------


def test_provider_is_taken_from_the_model_prefix() -> None:
    assert provider_for_model("openai/gpt-4o-mini") == "openai"
    assert provider_for_model("anthropic/claude-3-5-haiku-20241022") == "anthropic"


def test_bare_model_name_is_rejected() -> None:
    """A bare name would let LiteLLM guess the provider, and therefore guess
    which of the tenant's keys to spend. Force it to be explicit."""
    with pytest.raises(UnknownProviderError, match="provider-qualified"):
        provider_for_model("gpt-4o-mini")


def test_unsupported_provider_is_rejected() -> None:
    """Providers we have no credential kind for cannot be routed to — we would
    have nowhere to look up a key."""
    with pytest.raises(UnknownProviderError, match="unsupported provider"):
        provider_for_model("bedrock/anthropic.claude-v2")
    with pytest.raises(UnknownProviderError, match="unsupported provider"):
        provider_for_model("notaprovider/some-model")


# --- resolution -------------------------------------------------------------


async def test_key_is_loaded_from_the_tenant_vault() -> None:
    tenant_id = await _mk_tenant("byok")
    await _store_key(tenant_id, "llm_openai", "sk-test-tenant-key")

    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        creds = await load_credentials(session, tenant_id=tenant_id, provider="openai")

    assert creds is not None
    assert creds.api_key == "sk-test-tenant-key"
    assert creds.provider == "openai"


async def test_one_tenants_key_is_invisible_to_another() -> None:
    a = await _mk_tenant("byok-a")
    b = await _mk_tenant("byok-b")
    await _store_key(a, "llm_openai", "sk-tenant-a-only")

    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(b))
        creds = await load_credentials(session, tenant_id=b, provider="openai")
    assert creds is None, "tenant B must not see tenant A's key"


async def test_missing_key_raises_actionable_setup_error() -> None:
    """No key connected must fail loudly. The previous behaviour silently
    swapped in a fake client, so users got fabricated drafts with no error."""
    tenant_id = await _mk_tenant("byok-none")
    set_llm_client(None)  # disable the autouse test fake for this check
    try:
        factory = get_session_factory()
        async with factory() as session, session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            with pytest.raises(MissingLLMCredentialsError) as exc:
                await resolve_llm_client(
                    session, tenant_id=tenant_id, model="openai/gpt-4o-mini"
                )
    finally:
        set_llm_client(None)
    # The message is shown to the user, so it must say what to do.
    assert "Integrations" in str(exc.value)


async def test_env_var_takes_precedence_over_a_missing_stored_key(monkeypatch) -> None:
    """Single-user build: the operator's own env key satisfies any tenant,
    even one that never stored a row of its own — there is only one real
    workspace, so the env key IS that workspace's key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    tenant_id = await _mk_tenant("byok-env")
    set_llm_client(None)
    try:
        factory = get_session_factory()
        async with factory() as session, session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            client = await resolve_llm_client(
                session, tenant_id=tenant_id, model="openai/gpt-4o-mini"
            )
    finally:
        set_llm_client(None)
    assert isinstance(client, LiteLLMClient)
    assert client._credentials.api_key == "sk-env-key"  # private field; no public accessor exists


async def test_env_var_takes_precedence_over_a_stored_key(monkeypatch) -> None:
    """Env beats a stored row too, not just a missing one."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    tenant_id = await _mk_tenant("byok-env-over-stored")
    await _store_key(tenant_id, "llm_openai", "sk-stored-key")
    set_llm_client(None)
    try:
        factory = get_session_factory()
        async with factory() as session, session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            creds = await load_credentials(session, tenant_id=tenant_id, provider="openai")
    finally:
        set_llm_client(None)
    assert creds is not None
    assert creds.api_key == "sk-env-key"


async def test_resolved_client_is_bound_to_the_tenants_key() -> None:
    tenant_id = await _mk_tenant("byok-bound")
    await _store_key(tenant_id, "llm_anthropic", "sk-ant-tenant")
    set_llm_client(None)
    try:
        factory = get_session_factory()
        async with factory() as session, session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            client = await resolve_llm_client(
                session,
                tenant_id=tenant_id,
                model="anthropic/claude-3-5-haiku-20241022",
            )
    finally:
        set_llm_client(None)
    assert client.provider == "anthropic"  # type: ignore[union-attr]


# --- secret hygiene ---------------------------------------------------------


def test_credentials_repr_does_not_leak_the_key() -> None:
    """Tracebacks and log lines routinely render objects with repr()."""
    creds = LLMCredentials(provider="openai", api_key="sk-super-secret-value")
    assert "sk-super-secret-value" not in repr(creds)
    assert "***" in repr(creds)
