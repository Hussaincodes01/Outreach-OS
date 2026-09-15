"""GDPR endpoints in the single-user build: export stays, erasure is gone.

Erasure used to mark the only workspace's tenant `deleted`, which silently
stopped every sequence send (send_due only processes active tenants) with no
way back. Wiping all data is `docker compose down -v` instead.
"""
from __future__ import annotations

import json

import httpx


async def test_erasure_route_is_gone(client: httpx.AsyncClient) -> None:
    resp = await client.delete("/v1/gdpr/me")
    assert resp.status_code in (404, 405), resp.text


async def test_erasure_attempt_leaves_the_workspace_active(client: httpx.AsyncClient) -> None:
    await client.delete("/v1/gdpr/me")
    me = await client.get("/v1/tenants/me")
    assert me.status_code == 200, me.text
    assert me.json()["status"] == "active"


async def test_export_still_streams_workspace_data(client: httpx.AsyncClient) -> None:
    resp = await client.get("/v1/gdpr/export")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert all("table" in line and "data" in line for line in lines)
