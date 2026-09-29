"""Every business endpoint requires a valid bearer token again."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import jwt
from starlette.websockets import WebSocketDisconnect

from outreach_os.core import rate_limit
from outreach_os.core.auth import create_access_token, create_refresh_token
from outreach_os.core.config import get_settings
from outreach_os.main import app
from tests.conftest import bearer, signup, unique_email

PROTECTED = [
    ("get", "/v1/leads"),
    ("get", "/v1/mailboxes"),
    ("get", "/v1/credentials"),
    ("get", "/v1/tenants/me"),
    ("post", "/v1/drafts/generate"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_protected_routes_reject_missing_token(client: httpx.AsyncClient, method: str, path: str) -> None:
    resp = await getattr(client, method)(path)
    assert resp.status_code == 401, f"{path} -> {resp.status_code}"


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
async def test_health_stays_public(client: httpx.AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 200


# --- beyond the brief's minimum -------------------------------------------

# The only routes that may answer without a bearer token. Anything else
# showing up here is a business endpoint that forgot `get_current_user`.
PUBLIC_ROUTES = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/health/ready"),
    ("POST", "/v1/auth/signup"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/refresh"),
    ("POST", "/v1/auth/forgot-password"),
    ("POST", "/v1/auth/reset-password"),
    ("POST", "/v1/auth/verify-email"),
    ("POST", "/v1/webhooks/inbound-email"),
    ("GET", "/t/open/{send_id}.png"),
    ("GET", "/t/click/{send_id}"),
    ("GET", "/t/unsubscribe"),
    # Authenticates itself from `?token=` (browsers can't set WS headers).
    ("WS", "/v1/notifications/ws"),
}


def _routes_without_auth() -> set[tuple[str, str]]:
    from fastapi.routing import APIRoute, APIWebSocketRoute

    from outreach_os.api.deps import get_current_user

    def calls(dependant) -> set:
        out = set()
        for sub in dependant.dependencies:
            out.add(sub.call)
            out |= calls(sub)
        return out

    def walk(routes, prefix: str, inherited: set):
        for r in routes:
            ctx = getattr(r, "include_context", None)
            if ctx is not None:
                # `app.include_router(...)`: prefix and dependencies are
                # applied at include time, not stored on the routes.
                deps = {d.dependency for d in ctx.dependencies}
                yield from walk(ctx.included_router.routes, prefix + ctx.prefix, inherited | deps)
            else:
                yield prefix, r, inherited

    found: set[tuple[str, str]] = set()
    for prefix, route, inherited in walk(app.routes, "", set()):
        if not isinstance(route, (APIRoute, APIWebSocketRoute)):
            continue
        if get_current_user in calls(route.dependant) | inherited:
            continue
        methods = {"WS"} if isinstance(route, APIWebSocketRoute) else route.methods
        found |= {(m, prefix + route.path) for m in methods}
    return found


def test_only_the_public_allowlist_answers_without_a_token() -> None:
    assert _routes_without_auth() == PUBLIC_ROUTES



async def test_refresh_token_is_not_accepted_as_an_access_token(client: httpx.AsyncClient) -> None:
    acct = await signup(
        client, email=unique_email(), password="correct-horse-battery-staple", tenant_name="Typ"
    )
    resp = await client.get("/v1/tenants/me", headers=bearer(acct["refresh_token"]))
    assert resp.status_code == 401


async def test_token_signed_with_another_secret_is_rejected(client: httpx.AsyncClient) -> None:
    acct = await signup(
        client, email=unique_email(), password="correct-horse-battery-staple", tenant_name="Sig"
    )
    forged = jwt.encode(
        {"sub": acct["user_id"], "tid": acct["tenant_id"], "typ": "access", "role": "owner"},
        "an-entirely-different-secret-value",
        algorithm=get_settings().jwt_alg,
    )
    resp = await client.get("/v1/tenants/me", headers=bearer(forged))
    assert resp.status_code == 401


async def test_a_token_only_sees_its_own_workspace(client: httpx.AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="correct-horse-battery-staple", tenant_name="A")
    b = await signup(client, email=unique_email(), password="correct-horse-battery-staple", tenant_name="B")
    me_a = await client.get("/v1/tenants/me", headers=bearer(a["access_token"]))
    me_b = await client.get("/v1/tenants/me", headers=bearer(b["access_token"]))
    assert me_a.status_code == me_b.status_code == 200
    assert me_a.json()["id"] == a["tenant_id"]
    assert me_b.json()["id"] == b["tenant_id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/auth/login"),
        ("post", "/v1/auth/signup"),
        ("post", "/v1/auth/refresh"),
        ("post", "/v1/auth/forgot-password"),
        ("post", "/v1/auth/reset-password"),
        ("post", "/v1/auth/verify-email"),
    ],
)
async def test_auth_entry_points_need_no_token(client: httpx.AsyncClient, method: str, path: str) -> None:
    """An empty body is a validation error (422), never a 401."""
    resp = await getattr(client, method)(path, json={})
    assert resp.status_code == 422, f"{path} -> {resp.status_code}"


async def test_cors_allows_the_authorization_header(client: httpx.AsyncClient) -> None:
    resp = await client.options(
        "/v1/tenants/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code == 200, resp.text
    assert "authorization" in resp.headers["access-control-allow-headers"].lower()


# --- per-IP auth rate limits ------------------------------------------------


def test_auth_rate_limit_defaults_are_restored() -> None:
    assert rate_limit.AUTH_DEFAULTS == {
        "login": 10,
        "signup": 5,
        "refresh": 30,
        "webhook": 100,
        "password_reset": 3,
    }


async def test_login_is_rate_limited_per_ip(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(get_settings().auth_rate_limits_per_minute, "login", 2)
    rate_limit.reset_ip("127.0.0.1", "login")
    body = {"email": unique_email(), "password": "whatever-12345678"}
    codes = [(await client.post("/v1/auth/login", json=body)).status_code for _ in range(3)]
    rate_limit.reset_ip("127.0.0.1", "login")
    assert codes[:2] == [401, 401]
    assert codes[2] == 429


# --- WebSocket --------------------------------------------------------------


def test_notifications_websocket_rejects_a_missing_token() -> None:
    with pytest.raises(WebSocketDisconnect), TestClient(app).websocket_connect("/v1/notifications/ws") as ws:
        ws.receive_json()


def test_notifications_websocket_rejects_a_refresh_token() -> None:
    token = create_refresh_token(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        password_hash="!",
    )
    with pytest.raises(WebSocketDisconnect), TestClient(app).websocket_connect(
        f"/v1/notifications/ws?token={token}"
    ) as ws:
        ws.receive_json()


def test_notifications_websocket_accepts_an_access_token() -> None:
    token = create_access_token(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
    )
    with TestClient(app).websocket_connect(f"/v1/notifications/ws?token={token}") as ws:
        assert ws.receive_json()["event_key"] == "ws.connected"


# --- error mapping ----------------------------------------------------------


async def test_auth_error_maps_to_401() -> None:
    from starlette.requests import Request

    from outreach_os.core.errors import AuthError
    from outreach_os.main import _handle_domain_error

    request = Request({"type": "http", "method": "GET", "path": "/x", "headers": []})
    resp = await _handle_domain_error(request, AuthError("account suspended"))
    assert resp.status_code == 401
