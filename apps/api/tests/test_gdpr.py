"""GDPR endpoints: export stays, the old erasure route stays gone.

Erasure used to mark the workspace's tenant `deleted`, which silently
stopped every sequence send (send_due only processes active tenants) with no
way back.
"""
from __future__ import annotations

import json

import httpx


async def test_erasure_route_is_gone(authed_client: httpx.AsyncClient) -> None:
    resp = await authed_client.delete("/v1/gdpr/me")
    assert resp.status_code in (404, 405), resp.text


async def test_erasure_attempt_leaves_the_workspace_active(authed_client: httpx.AsyncClient) -> None:
    await authed_client.delete("/v1/gdpr/me")
    me = await authed_client.get("/v1/tenants/me")
    assert me.status_code == 200, me.text
    assert me.json()["status"] == "active"


async def test_export_still_streams_workspace_data(authed_client: httpx.AsyncClient) -> None:
    resp = await authed_client.get("/v1/gdpr/export")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert all("table" in line and "data" in line for line in lines)


async def test_export_includes_the_audit_trail(authed_client: httpx.AsyncClient) -> None:
    """Signup writes hash-chained audit rows (bytea columns); the export must
    encode them instead of failing mid-stream."""
    resp = await authed_client.get("/v1/gdpr/export")
    assert resp.status_code == 200, resp.text
    tables = {json.loads(line)["table"] for line in resp.text.splitlines() if line.strip()}
    assert "audit_event" in tables
