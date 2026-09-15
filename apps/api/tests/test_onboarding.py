"""Self-serve onboarding checklist.

The one property that matters: the checklist reflects *live* workspace state,
not a stored flag. A user who removes their API key must see that step reopen —
a cached tick would leave them looking at a green checklist and a broken app.
"""
from __future__ import annotations

import pytest

from tests.conftest import bearer, signup, unique_email

pytestmark = pytest.mark.asyncio


def _step(payload: dict, key: str) -> dict:
    return next(s for s in payload["steps"] if s["key"] == key)


async def test_new_workspace_is_not_ready_and_points_at_the_first_step(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Fresh",
    )
    resp = await client.get("/v1/onboarding", headers=bearer(a["access_token"]))
    assert resp.status_code == 200
    body = resp.json()

    assert body["ready"] is False
    assert body["next_step_key"] == "llm_key", "BYOK is the first thing to do"
    assert _step(body, "llm_key")["done"] is False
    # Every step must tell the UI where to send the user.
    assert all(s["href"].startswith("/") for s in body["steps"])


async def test_connecting_a_key_completes_the_step(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Connects",
    )
    headers = bearer(a["access_token"])

    before = await client.get("/v1/onboarding", headers=headers)
    assert _step(before.json(), "llm_key")["done"] is False

    created = await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_openai",
            "label": "My OpenAI key",
            "secret_payload": {"api_key": "sk-test-not-real"},
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    after = await client.get("/v1/onboarding", headers=headers)
    body = after.json()
    assert _step(body, "llm_key")["done"] is True
    # Storing a key is not the same as proving it works.
    assert _step(body, "llm_verified")["done"] is False
    assert body["next_step_key"] != "llm_key"


async def test_removing_the_key_reopens_the_step(client) -> None:
    """Derived-not-stored: the regression this guards against is a checklist
    that stays green after the thing it describes is gone."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Removes",
    )
    headers = bearer(a["access_token"])
    created = await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_openai",
            "label": "temp",
            "secret_payload": {"api_key": "sk-test-not-real"},
        },
        headers=headers,
    )
    cred_id = created.json()["id"]
    assert _step(
        (await client.get("/v1/onboarding", headers=headers)).json(), "llm_key"
    )["done"] is True

    deleted = await client.delete(f"/v1/credentials/{cred_id}", headers=headers)
    assert deleted.status_code == 204

    body = (await client.get("/v1/onboarding", headers=headers)).json()
    assert _step(body, "llm_key")["done"] is False
    assert body["ready"] is False


async def test_dismiss_hides_the_checklist_without_faking_progress(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Dismisses",
    )
    headers = bearer(a["access_token"])
    resp = await client.post(
        "/v1/onboarding/dismiss", json={"dismissed": True}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dismissed"] is True
    # Dismissing is cosmetic; the work is still outstanding.
    assert body["ready"] is False
    assert _step(body, "llm_key")["done"] is False


# --- workspace model selection ---------------------------------------------


async def test_choosing_a_model_without_its_key_is_refused(client) -> None:
    """Otherwise the failure surfaces later, as a broken campaign."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="NoKey",
    )
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={"default_llm_model": "anthropic/claude-3-5-haiku-20241022"},
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 428, resp.text
    assert "anthropic" in resp.json()["detail"].lower()


async def test_choosing_a_model_works_once_its_key_is_connected(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="HasKey",
    )
    headers = bearer(a["access_token"])
    await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_anthropic",
            "label": "ant",
            "secret_payload": {"api_key": "sk-ant-test"},
        },
        headers=headers,
    )
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={"default_llm_model": "anthropic/claude-3-5-haiku-20241022"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_llm_model"] == "anthropic/claude-3-5-haiku-20241022"


async def test_unqualified_model_name_is_rejected(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="BadModel",
    )
    resp = await client.put(
        "/v1/onboarding/llm-settings",
        json={"default_llm_model": "gpt-4o-mini"},
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 422, resp.text


async def test_models_of_a_provider_keyed_in_env_are_available(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key in .env is a connected key. The model picker must not grey out its
    models just because no credential row exists."""
    from outreach_os.core import env_keys

    monkeypatch.setenv("GROQ_API_KEY", "gsk-env-test")
    env_keys.reset_env_cache()

    resp = await client.get("/v1/onboarding/llm-settings")
    assert resp.status_code == 200, resp.text
    availability = {m["provider"]: m["available"] for m in resp.json()["models"]}
    assert availability["groq"] is True
    assert availability["openai"] is False


async def test_env_keyed_compatible_endpoint_accepts_custom_models(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gateway configured only through .env must still let the user type a
    model name, or it cannot be selected at all."""
    from outreach_os.core import env_keys

    monkeypatch.setenv("OPENAI_LIKE_API_KEY", "sk-gateway-test")
    monkeypatch.setenv("OPENAI_LIKE_API_BASE", "https://gateway.example.com/v1")
    env_keys.reset_env_cache()

    resp = await client.get("/v1/onboarding/llm-settings")
    assert resp.status_code == 200, resp.text
    assert "openai_like" in resp.json()["custom_model_providers"]


# --- provider catalogue -----------------------------------------------------


async def test_providers_endpoint_reports_connection_state(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Providers",
    )
    headers = bearer(a["access_token"])
    resp = await client.get("/v1/credentials/providers", headers=headers)
    assert resp.status_code == 200
    providers = {p["provider"]: p for p in resp.json()}
    assert "openai" in providers
    assert providers["openai"]["connected"] is False
    # The UI needs somewhere to send users to fetch a key.
    assert providers["openai"]["console_url"].startswith("https://")

    await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_openai",
            "label": "k",
            "secret_payload": {"api_key": "sk-test"},
        },
        headers=headers,
    )
    resp = await client.get("/v1/credentials/providers", headers=headers)
    providers = {p["provider"]: p for p in resp.json()}
    assert providers["openai"]["connected"] is True
    assert providers["openai"]["last_verified_at"] is None


async def test_unknown_credential_kind_is_rejected(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="BadKind",
    )
    resp = await client.post(
        "/v1/credentials",
        json={"kind": "not_a_real_provider", "label": "x", "secret_payload": {"api_key": "y"}},
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 422, resp.text
