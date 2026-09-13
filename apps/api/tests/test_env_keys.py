"""Provider keys come from environment / .env, ahead of stored credentials."""
from __future__ import annotations

import httpx
import pytest

from outreach_os.core import env_keys
from outreach_os.core.llm import set_llm_client
from outreach_os.services import credential_lookup, llm_credentials
from outreach_os.services.local_workspace import LOCAL_TENANT_ID

pytestmark = pytest.mark.asyncio


def test_var_names() -> None:
    assert env_keys.provider_key_var("openai") == "OPENAI_API_KEY"
    assert env_keys.provider_key_var("together-ai") == "TOGETHER_AI_API_KEY"
    assert env_keys.provider_base_var("ollama") == "OLLAMA_API_BASE"
    assert env_keys.scraping_key_var("serper") == "SERPER_API_KEY"


def test_env_value_reads_process_env_then_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    (tmp_path / ".env").write_text("SERPER_API_KEY=from-dotenv\nOPENAI_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(env_keys, "_dotenv_path", lambda: tmp_path / ".env")
    env_keys.reset_env_cache()
    assert env_keys.env_value("SERPER_API_KEY") == "from-dotenv"
    assert env_keys.env_value("OPENAI_API_KEY") is None  # empty counts as unset
    monkeypatch.setenv("SERPER_API_KEY", "from-process")
    assert env_keys.env_value("SERPER_API_KEY") == "from-process"


def test_env_credentials_for_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    creds = llm_credentials.env_credentials("openai")
    assert creds is not None
    assert creds.api_key == "sk-env"


def test_env_credentials_none_when_unset() -> None:
    assert llm_credentials.env_credentials("openai") is None


def test_env_credentials_for_keyless_provider_needs_only_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama takes no key, only a base URL — confirms env wiring respects
    each provider's requires_api_key/requires_api_base flags."""
    assert llm_credentials.env_credentials("ollama") is None
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")
    creds = llm_credentials.env_credentials("ollama")
    assert creds is not None
    assert creds.api_base == "http://localhost:11434"


async def test_resolve_prefers_env(monkeypatch: pytest.MonkeyPatch, scoped_session) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    set_llm_client(None)
    client = await llm_credentials.resolve_llm_client(
        scoped_session, tenant_id=LOCAL_TENANT_ID, model="openai/gpt-4o-mini"
    )
    assert isinstance(client, llm_credentials.LiteLLMClient)
    assert client._credentials.api_key == "sk-env"  # private field; no public accessor exists


async def test_provider_listing_without_key(client: httpx.AsyncClient) -> None:
    """No key anywhere (env or stored) -> the listing shows not-connected.

    The 428-on-missing-key behaviour itself is covered by the existing
    test_missing_key_raises_actionable_setup_error in test_byok_credentials.py.
    """
    set_llm_client(None)
    resp = await client.get("/v1/credentials/providers")
    assert resp.status_code == 200
    openai = next(p for p in resp.json() if p["provider"] == "openai")
    assert openai["connected"] is False
    assert openai["configured_via"] is None
    assert openai["env_var"] == "OPENAI_API_KEY"
    assert openai["env_base_var"] == "OPENAI_API_BASE"


async def test_provider_listing_reports_env(monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    resp = await client.get("/v1/credentials/providers")
    openai = next(p for p in resp.json() if p["provider"] == "openai")
    assert openai["connected"] is True
    assert openai["configured_via"] == "env"


async def test_scraping_keys_from_env(
    monkeypatch: pytest.MonkeyPatch, scoped_session, client: httpx.AsyncClient
) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "serp-env")
    got = await credential_lookup.get_credential_secrets(
        scoped_session, tenant_id=LOCAL_TENANT_ID, kinds=["serper", "proxycurl"]
    )
    assert got == {"serper": "serp-env"}
    listing = (await client.get("/v1/credentials/scraping")).json()
    assert {"kind": "serper", "env_var": "SERPER_API_KEY", "configured": True} in listing
    assert {"kind": "proxycurl", "env_var": "PROXYCURL_API_KEY", "configured": False} in listing


# --- POST /v1/credentials/providers/{provider}/test ------------------------


async def test_test_unknown_provider_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/v1/credentials/providers/not-a-real-provider/test")
    assert resp.status_code == 404


async def test_test_without_any_key_is_428(client: httpx.AsyncClient) -> None:
    """Neither env nor a stored row -> 428, never a fabricated "ok"."""
    resp = await client.post("/v1/credentials/providers/openai/test")
    assert resp.status_code == 428, resp.text


async def test_test_env_key_succeeds_and_is_reflected_in_the_listing(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    """A successful Test stamps tenant.onboarding_state["verified_providers"],
    and the providers listing then reports last_verified_at for that env-
    configured provider (R3's "verified timestamp" requirement)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")

    async def _fake_probe(client: object, model: str) -> None:
        return None

    monkeypatch.setattr(llm_credentials, "_achat_probe", _fake_probe)

    resp = await client.post("/v1/credentials/providers/openai/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["message"]

    listing = (await client.get("/v1/credentials/providers")).json()
    openai = next(p for p in listing if p["provider"] == "openai")
    assert openai["configured_via"] == "env"
    assert openai["last_verified_at"] is not None


async def test_test_reports_failure_without_crashing(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-bad")

    async def _fake_probe(client: object, model: str) -> None:
        from outreach_os.core.llm import LLMAuthError

        raise LLMAuthError("invalid api key")

    monkeypatch.setattr(llm_credentials, "_achat_probe", _fake_probe)

    resp = await client.post("/v1/credentials/providers/openai/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False

    listing = (await client.get("/v1/credentials/providers")).json()
    openai = next(p for p in listing if p["provider"] == "openai")
    assert openai["last_verified_at"] is None
