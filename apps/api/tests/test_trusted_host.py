"""The API only answers requests addressed to an allowed Host.

There is no login, so a DNS-rebinding page in the operator's browser must not
be able to reach the API under a hostname it controls. TrustedHostMiddleware
rejects any Host not in ALLOWED_HOSTS (default: localhost, 127.0.0.1).
"""
from __future__ import annotations

import httpx

from outreach_os.core.config import Settings


async def test_unknown_host_is_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health", headers={"Host": "evil.example"})
    assert resp.status_code == 400, resp.text


async def test_unknown_host_is_rejected_on_api_routes(client: httpx.AsyncClient) -> None:
    resp = await client.get("/v1/tenants/me", headers={"Host": "evil.example:8000"})
    assert resp.status_code == 400, resp.text


async def test_localhost_is_allowed(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health", headers={"Host": "localhost"})
    assert resp.status_code == 200, resp.text


async def test_localhost_with_port_is_allowed(client: httpx.AsyncClient) -> None:
    """The browser calls NEXT_PUBLIC_API_URL=http://localhost:8000, so the Host
    header is `localhost:8000`; the middleware matches on the hostname."""
    resp = await client.get("/health", headers={"Host": "localhost:8000"})
    assert resp.status_code == 200, resp.text


async def test_loopback_ip_is_allowed(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health", headers={"Host": "127.0.0.1:8000"})
    assert resp.status_code == 200, resp.text


def test_allowed_hosts_default_is_localhost_only(monkeypatch) -> None:
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    assert Settings(_env_file=None).allowed_hosts == ["localhost", "127.0.0.1"]


def test_allowed_hosts_accepts_comma_separated(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost, 127.0.0.1 ,outreach.lan")
    assert Settings(_env_file=None).allowed_hosts == ["localhost", "127.0.0.1", "outreach.lan"]


def test_allowed_hosts_accepts_json_array(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", '["localhost", "192.168.1.20"]')
    assert Settings(_env_file=None).allowed_hosts == ["localhost", "192.168.1.20"]
