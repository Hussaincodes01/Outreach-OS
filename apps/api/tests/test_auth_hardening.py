"""One account per email address, and refresh tokens that can be revoked.

Two properties a public signup needs:

1. An email address belongs to at most one account. Login and password reset
   resolve the address across every workspace, so a second account with the
   same address (e.g. a stranger signing up with a victim's email) would make
   both resolve to an arbitrary row.
2. A refresh token dies when the password changes or the user is deactivated.
   Otherwise resetting a compromised password leaves the attacker able to mint
   access tokens for the whole refresh lifetime.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from outreach_os.core.db import get_session_factory
from outreach_os.core.mailer import StubMailer, set_transactional_mailer
from outreach_os.core.tenancy import set_tenant_for_session
from tests.conftest import bearer, signup, unique_email

_PASSWORD = "correct-horse-battery-staple"
_OTHER_PASSWORD = "a-completely-different-passphrase"


@pytest.fixture
def mailer() -> StubMailer:
    stub = StubMailer()
    set_transactional_mailer(stub)
    yield stub
    set_transactional_mailer(None)


def _token_from_last_email(stub: StubMailer) -> str:
    body = stub.sent[-1].body_text
    start = body.index("token=") + len("token=")
    return body[start:].split()[0].strip()


# --- one account per email ------------------------------------------------


@pytest.mark.parametrize("second_spelling", ["same", "upper"])
async def test_second_signup_with_the_same_email_is_refused(
    client: httpx.AsyncClient, second_spelling: str
) -> None:
    email = unique_email()
    first = await signup(client, email=email, password=_PASSWORD, tenant_name="Owner Co")

    again = email if second_spelling == "same" else email.upper()
    resp = await client.post(
        "/v1/auth/signup",
        json={"email": again, "password": _OTHER_PASSWORD, "tenant_name": "Squatter Co"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "an account with this email already exists"

    # The refused attempt left no second workspace or user behind.
    async with get_session_factory()() as session:
        tenants = (
            await session.execute(text("SELECT count(*) FROM tenant WHERE name = 'Squatter Co'"))
        ).scalar_one()
    assert tenants == 0

    # Login still resolves to the original account, with the original password.
    login = await client.post("/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["tenant_id"] == first["tenant_id"]
    assert login.json()["user_id"] == first["user_id"]
    squatter = await client.post(
        "/v1/auth/login", json={"email": email, "password": _OTHER_PASSWORD}
    )
    assert squatter.status_code == 401


async def test_the_database_refuses_the_same_email_in_another_workspace() -> None:
    """The unique index is the real guarantee; the signup pre-check only gives
    a friendly message. Case differences must not slip past it."""
    email = unique_email()
    factory = get_session_factory()
    tenant_ids = [uuid.uuid4(), uuid.uuid4()]
    for tid in tenant_ids:
        async with factory() as session, session.begin():
            await session.execute(
                text("INSERT INTO tenant (id, slug, name) VALUES (:id, :slug, 'T')"),
                {"id": tid, "slug": f"t-{tid.hex[:10]}"},
            )

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_ids[0]))
        await session.execute(
            text("INSERT INTO app_user (tenant_id, email, password_hash) VALUES (:t, :e, '!')"),
            {"t": tenant_ids[0], "e": email},
        )

    async with factory() as session:
        await set_tenant_for_session(session, str(tenant_ids[1]))
        insert = text(
            "INSERT INTO app_user (tenant_id, email, password_hash) VALUES (:t, :e, '!')"
        )
        with pytest.raises(IntegrityError, match="uq_app_user_email_lower"):
            await session.execute(insert, {"t": tenant_ids[1], "e": email.upper()})
        await session.rollback()


async def test_a_signup_that_loses_the_race_gets_409_not_500(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent signups can both pass the pre-check; the loser must hit
    the unique index and still get a clean 409."""
    from outreach_os.services import user_service

    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Winner Co")

    async def _nobody_yet(session, address):  # the pre-check ran before the winner committed
        return None

    monkeypatch.setattr(user_service, "lookup_user_by_email", _nobody_yet)
    resp = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": _OTHER_PASSWORD, "tenant_name": "Loser Co"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "an account with this email already exists"


# --- revocable refresh tokens ----------------------------------------------


async def test_a_normal_refresh_still_works(client: httpx.AsyncClient) -> None:
    acct = await signup(client, email=unique_email(), password=_PASSWORD, tenant_name="R Co")
    resp = await client.post("/v1/auth/refresh", json={"refresh_token": acct["refresh_token"]})
    assert resp.status_code == 200, resp.text
    me = await client.get("/v1/auth/me", headers=bearer(resp.json()["access_token"]))
    assert me.status_code == 200


async def test_password_reset_revokes_existing_refresh_tokens(
    client: httpx.AsyncClient, mailer: StubMailer
) -> None:
    email = unique_email()
    acct = await signup(client, email=email, password=_PASSWORD, tenant_name="Reset Co")
    mailer.sent.clear()
    await client.post("/v1/auth/forgot-password", json={"email": email})
    reset = await client.post(
        "/v1/auth/reset-password",
        json={"token": _token_from_last_email(mailer), "new_password": _OTHER_PASSWORD},
    )
    assert reset.status_code == 200, reset.text

    stale = await client.post("/v1/auth/refresh", json={"refresh_token": acct["refresh_token"]})
    assert stale.status_code == 401, stale.text

    login = await client.post("/v1/auth/login", json={"email": email, "password": _OTHER_PASSWORD})
    assert login.status_code == 200, login.text
    fresh = await client.post(
        "/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    assert fresh.status_code == 200, fresh.text


async def test_a_deactivated_user_cannot_refresh(client: httpx.AsyncClient) -> None:
    acct = await signup(client, email=unique_email(), password=_PASSWORD, tenant_name="Off Co")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, acct["tenant_id"])
        await session.execute(
            text("UPDATE app_user SET is_active = false WHERE id = :id"), {"id": acct["user_id"]}
        )
    resp = await client.post("/v1/auth/refresh", json={"refresh_token": acct["refresh_token"]})
    assert resp.status_code == 401, resp.text


async def test_a_refresh_token_for_a_deleted_user_is_refused(client: httpx.AsyncClient) -> None:
    acct = await signup(client, email=unique_email(), password=_PASSWORD, tenant_name="Gone Co")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, acct["tenant_id"])
        await session.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": acct["user_id"]})
    resp = await client.post("/v1/auth/refresh", json={"refresh_token": acct["refresh_token"]})
    assert resp.status_code == 401, resp.text
