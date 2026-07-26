"""THE critical test: tenant A must not be able to see tenant B's data,
under any of the common attack patterns (list, fetch-by-id, SQL
injection, missing app.current_tenant). CI MUST fail if this test is
removed or skipped.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session

from .conftest import bearer, signup, unique_email

pytestmark = pytest.mark.asyncio


async def test_signup_creates_separate_tenants(client: AsyncClient) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    b = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Globex",
        tenant_slug="globex",
    )
    assert a["access_token"]
    assert b["access_token"]
    assert a["access_token"] != b["access_token"]


async def test_list_credentials_only_returns_own_tenant(
    client: AsyncClient,
) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    b = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Globex",
        tenant_slug="globex",
    )

    # Tenant A adds a credential.
    resp = await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_openai",
            "label": "A's key",
            "secret_payload": {"api_key": "sk-a-xxx"},
        },
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 201, resp.text
    a_cred_id = resp.json()["id"]

    # Tenant A sees exactly one.
    resp = await client.get("/v1/credentials", headers=bearer(a["access_token"]))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == a_cred_id

    # Tenant B sees zero.
    resp = await client.get("/v1/credentials", headers=bearer(b["access_token"]))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_cross_tenant_fetch_by_id_returns_404_not_403(
    client: AsyncClient,
) -> None:
    """We must NEVER reveal that the row exists. 404 (not found) is the
    correct response; 403 (forbidden) would leak existence."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    b = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Globex",
        tenant_slug="globex",
    )
    resp = await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_anthropic",
            "label": "A's claude key",
            "secret_payload": {"api_key": "sk-ant-xxx"},
        },
        headers=bearer(a["access_token"]),
    )
    a_cred_id = resp.json()["id"]

    # Tenant B tries to test A's credential by id — must 404.
    resp = await client.post(
        f"/v1/credentials/{a_cred_id}/test",
        headers=bearer(b["access_token"]),
    )
    assert resp.status_code == 404, (
        f"Cross-tenant test returned {resp.status_code}; "
        "this leaks the existence of another tenant's data."
    )

    # Tenant B tries to delete A's credential — must 404.
    resp = await client.delete(
        f"/v1/credentials/{a_cred_id}",
        headers=bearer(b["access_token"]),
    )
    assert resp.status_code == 404

    # Confirm A's credential is still there.
    resp = await client.get("/v1/credentials", headers=bearer(a["access_token"]))
    assert len(resp.json()) == 1


async def test_audit_log_only_returns_own_tenant(client: AsyncClient) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    b = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Globex",
        tenant_slug="globex",
    )
    # A does an action that writes audit.
    await client.post(
        "/v1/credentials",
        json={
            "kind": "serper",
            "label": "A",
            "secret_payload": {"api_key": "k"},
        },
        headers=bearer(a["access_token"]),
    )
    # B does a different one.
    await client.post(
        "/v1/credentials",
        json={
            "kind": "serper",
            "label": "B",
            "secret_payload": {"api_key": "k"},
        },
        headers=bearer(b["access_token"]),
    )

    resp_a = await client.get("/v1/audit", headers=bearer(a["access_token"]))
    resp_b = await client.get("/v1/audit", headers=bearer(b["access_token"]))

    actions_a = {row["action"] for row in resp_a.json()["items"]}
    actions_b = {row["action"] for row in resp_b.json()["items"]}

    assert "credential.created" in actions_a
    assert "credential.created" in actions_b
    assert len(resp_a.json()["items"]) == len(resp_b.json()["items"])


async def test_rls_blocks_unscoped_query(client: AsyncClient) -> None:
    """Open a session with NO app.current_tenant set and try to read
    credentials directly. With RLS enabled, the query should return
    zero rows because the policy filter matches nothing."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="RLSTest",
        tenant_slug="rls",
    )
    await client.post(
        "/v1/credentials",
        json={
            "kind": "llm_openai",
            "label": "K",
            "secret_payload": {"api_key": "k"},
        },
        headers=bearer(a["access_token"]),
    )

    async with session_scope() as session:
        # Confirm the setting is unset.
        result = await session.execute(
            text("SELECT current_setting('app.current_tenant', true)")
        )
        assert result.scalar() in (None, "")

        result = await session.execute(text("SELECT count(*) FROM credential"))
        count = result.scalar()
        assert count == 0, (
            f"RLS failed: unscoped session saw {count} rows from another tenant"
        )


async def test_rls_blocks_injection_that_drops_where_clause(
    client: AsyncClient,
) -> None:
    """Simulate a bug in app code that builds a query without a
    tenant_id WHERE clause. RLS must still filter."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Inj",
        tenant_slug="inj",
    )
    b = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Inj2",
        tenant_slug="inj2",
    )
    ra = await client.post(
        "/v1/credentials",
        json={
            "kind": "serper",
            "label": "a",
            "secret_payload": {"api_key": "key-a"},
        },
        headers=bearer(a["access_token"]),
    )
    assert ra.status_code == 201, ra.text
    rb = await client.post(
        "/v1/credentials",
        json={
            "kind": "serper",
            "label": "b",
            "secret_payload": {"api_key": "key-b"},
        },
        headers=bearer(b["access_token"]),
    )
    assert rb.status_code == 201, rb.text

    async with session_scope() as session:
        await set_tenant_for_session(session, str(b["tenant_id"]))
        rows = (
            await session.execute(
                text("SELECT label FROM credential")  # no WHERE clause
            )
        ).scalars().all()
        labels = sorted(rows)
        assert labels == ["b"], f"RLS leak: saw labels {labels!r}"
