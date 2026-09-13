"""The API runs as one built-in workspace: no Authorization header needed."""
from __future__ import annotations

import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text

from outreach_os.api.deps import get_current_user
from outreach_os.core.db import get_engine
from outreach_os.main import app
from outreach_os.services.local_workspace import (
    LOCAL_TENANT_ID,
    LOCAL_USER_ID,
    ensure_local_workspace,
    reset_local_workspace_cache,
)


async def test_tenant_me_works_without_authorization(client: httpx.AsyncClient) -> None:
    resp = await client.get("/v1/tenants/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(LOCAL_TENANT_ID)
    assert body["slug"] == "local"
    assert body["name"] == "My Workspace"


async def test_real_dependency_needs_no_header(client: httpx.AsyncClient) -> None:
    """Without the test-only override, a bare request still runs as the local workspace."""
    override = app.dependency_overrides.pop(get_current_user)
    try:
        resp = await client.get("/v1/tenants/me")
    finally:
        app.dependency_overrides[get_current_user] = override
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(LOCAL_TENANT_ID)


async def test_ensure_local_workspace_is_idempotent() -> None:
    reset_local_workspace_cache()
    await ensure_local_workspace()
    reset_local_workspace_cache()
    await ensure_local_workspace()
    async with get_engine().connect() as conn:
        tenants = (
            await conn.execute(text("SELECT count(*) FROM tenant WHERE id = :id"), {"id": LOCAL_TENANT_ID})
        ).scalar_one()
    assert tenants == 1


async def test_writes_are_scoped_to_local_workspace(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/v1/icps",
        json={"name": "Local ICP", "description": "d", "titles": ["CTO"]},
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["tenant_id"] == str(LOCAL_TENANT_ID)


async def test_auth_routes_are_gone(client: httpx.AsyncClient) -> None:
    assert (await client.post("/v1/auth/login", json={})).status_code == 404
    assert (await client.post("/v1/auth/signup", json={})).status_code == 404
    assert (await client.get("/v1/users")).status_code == 404


async def test_notifications_websocket_connects_without_token() -> None:
    # Create the rows on this event loop; the TestClient runs the app on its own.
    await ensure_local_workspace()
    with TestClient(app).websocket_connect("/v1/notifications/ws") as ws:
        assert ws.receive_json()["event_key"] == "ws.connected"


def test_local_ids_are_fixed() -> None:
    assert uuid.UUID("00000000-0000-4000-8000-000000000001") == LOCAL_TENANT_ID
    assert uuid.UUID("00000000-0000-4000-8000-000000000002") == LOCAL_USER_ID
