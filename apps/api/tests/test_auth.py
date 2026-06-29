"""Auth flow tests: signup, login, refresh, me, error cases."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from .conftest import bearer, signup, unique_email


pytestmark = pytest.mark.asyncio


async def test_signup_then_login(client: AsyncClient) -> None:
    email = unique_email()
    await signup(
        client,
        email=email,
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    resp = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(client: AsyncClient) -> None:
    email = unique_email()
    await signup(
        client,
        email=email,
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    resp = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": "WRONG-PASSWORD-XYZZY"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/auth/login",
        json={"email": unique_email(), "password": "whatever-12345678"},
    )
    assert resp.status_code == 401


async def test_refresh_returns_new_access_token(client: AsyncClient) -> None:
    pair = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    resp = await client.post(
        "/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["access_token"] != pair["access_token"]


async def test_refresh_with_access_token_rejected(client: AsyncClient) -> None:
    pair = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    resp = await client.post(
        "/v1/auth/refresh", json={"refresh_token": pair["access_token"]}
    )
    assert resp.status_code == 401


async def test_me_returns_authenticated_user(client: AsyncClient) -> None:
    email = unique_email()
    pair = await signup(
        client,
        email=email,
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    resp = await client.get("/v1/auth/me", headers=bearer(pair["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == email
    assert body["role"] == "owner"


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_garbage_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/v1/auth/me", headers=bearer("not-a-jwt"))
    assert resp.status_code == 401


async def test_signup_rejects_weak_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/auth/signup",
        json={
            "email": unique_email(),
            "password": "short",
            "tenant_name": "Acme",
        },
    )
    assert resp.status_code == 422


async def test_signup_rejects_duplicate_slug(client: AsyncClient) -> None:
    await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    resp = await client.post(
        "/v1/auth/signup",
        json={
            "email": unique_email(),
            "password": "correct-horse-battery-staple",
            "tenant_name": "Other",
            "tenant_slug": "acme",
        },
    )
    assert resp.status_code == 409
