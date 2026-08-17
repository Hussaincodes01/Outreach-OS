"""Password reset and email verification.

These are security-sensitive, so the tests assert the properties rather than
the happy path alone: reset links must be single-use, must not leak which
addresses have accounts, and must not become a way to weaken a password.
"""
from __future__ import annotations

import pytest

from outreach_os.core.auth import (
    TokenError,
    create_password_reset_token,
    decode_password_reset_token,
    hash_password,
)
from outreach_os.core.mailer import StubMailer, set_transactional_mailer
from tests.conftest import bearer, signup, unique_email

pytestmark = pytest.mark.asyncio

_PASSWORD = "correct-horse-battery-staple"
_NEW_PASSWORD = "a-completely-different-passphrase"


@pytest.fixture(autouse=True)
def mailer() -> StubMailer:
    """Capture outbound mail so tests can read the link that was sent."""
    stub = StubMailer()
    set_transactional_mailer(stub)
    yield stub
    set_transactional_mailer(None)


def _token_from_last_email(stub: StubMailer) -> str:
    assert stub.sent, "no email was sent"
    body = stub.sent[-1].body_text
    marker = "token="
    start = body.index(marker) + len(marker)
    return body[start:].split()[0].strip()


# --- token mechanics --------------------------------------------------------


async def test_reset_token_dies_once_the_password_changes() -> None:
    """This is what makes a link single-use without a tokens table: the token
    carries a fingerprint of the password hash it was issued against."""
    old_hash = hash_password(_PASSWORD)
    token = create_password_reset_token(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        password_hash=old_hash,
    )
    # Valid against the hash it was issued for.
    decode_password_reset_token(token, password_hash=old_hash)

    new_hash = hash_password(_NEW_PASSWORD)
    with pytest.raises(TokenError, match="already been used"):
        decode_password_reset_token(token, password_hash=new_hash)


async def test_reset_token_is_not_accepted_as_an_access_token(client) -> None:
    """Token types must not be interchangeable, or a reset link would be a
    login bypass."""
    token = create_password_reset_token(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        password_hash=hash_password(_PASSWORD),
    )
    resp = await client.get("/v1/auth/me", headers=bearer(token))
    assert resp.status_code == 401


# --- forgot password --------------------------------------------------------


async def test_forgot_password_does_not_reveal_whether_an_account_exists(
    client, mailer
) -> None:
    """Any difference here turns the endpoint into an enumeration oracle."""
    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Recover Co")

    known = await client.post("/v1/auth/forgot-password", json={"email": email})
    unknown = await client.post(
        "/v1/auth/forgot-password", json={"email": unique_email()}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


async def test_forgot_password_emails_a_working_link(client, mailer) -> None:
    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Link Co")
    mailer.sent.clear()

    resp = await client.post("/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 202
    assert len(mailer.sent) == 1
    assert mailer.sent[0].to_email == email
    assert "/reset-password?token=" in mailer.sent[0].body_text


async def test_no_email_is_sent_for_an_unknown_address(client, mailer) -> None:
    mailer.sent.clear()
    await client.post("/v1/auth/forgot-password", json={"email": unique_email()})
    assert mailer.sent == []


# --- reset ------------------------------------------------------------------


async def test_reset_changes_the_password_and_old_one_stops_working(
    client, mailer
) -> None:
    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Reset Co")
    mailer.sent.clear()
    await client.post("/v1/auth/forgot-password", json={"email": email})
    token = _token_from_last_email(mailer)

    resp = await client.post(
        "/v1/auth/reset-password", json={"token": token, "new_password": _NEW_PASSWORD}
    )
    assert resp.status_code == 200, resp.text

    old = await client.post(
        "/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert old.status_code == 401
    new = await client.post(
        "/v1/auth/login", json={"email": email, "password": _NEW_PASSWORD}
    )
    assert new.status_code == 200


async def test_a_reset_link_cannot_be_replayed(client, mailer) -> None:
    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Replay Co")
    mailer.sent.clear()
    await client.post("/v1/auth/forgot-password", json={"email": email})
    token = _token_from_last_email(mailer)

    first = await client.post(
        "/v1/auth/reset-password", json={"token": token, "new_password": _NEW_PASSWORD}
    )
    assert first.status_code == 200
    second = await client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": "yet-another-passphrase-here"},
    )
    assert second.status_code == 400
    assert "already been used" in second.json()["detail"]


async def test_reset_enforces_the_password_floor(client, mailer) -> None:
    """A reset must not be a route around the signup password policy."""
    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Weak Co")
    mailer.sent.clear()
    await client.post("/v1/auth/forgot-password", json={"email": email})
    token = _token_from_last_email(mailer)

    resp = await client.post(
        "/v1/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert resp.status_code == 422


async def test_garbage_token_is_rejected(client) -> None:
    resp = await client.post(
        "/v1/auth/reset-password",
        json={"token": "not-a-jwt", "new_password": _NEW_PASSWORD},
    )
    assert resp.status_code == 400


# --- email verification -----------------------------------------------------


async def test_signup_sends_a_verification_email(client, mailer) -> None:
    mailer.sent.clear()
    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Verify Co")
    assert any("/verify-email?token=" in m.body_text for m in mailer.sent)


async def test_new_users_start_unverified_and_can_confirm(client, mailer) -> None:
    mailer.sent.clear()
    email = unique_email()
    auth = await signup(client, email=email, password=_PASSWORD, tenant_name="Confirm Co")
    headers = bearer(auth["access_token"])

    before = (await client.get("/v1/auth/me", headers=headers)).json()
    assert before["email_verified_at"] is None

    token = _token_from_last_email(mailer)
    resp = await client.post("/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text

    after = (await client.get("/v1/auth/me", headers=headers)).json()
    assert after["email_verified_at"] is not None


async def test_unverified_users_are_not_locked_out(client, mailer) -> None:
    """Verification is a nudge, not a gate — locking a paying customer out
    because an email hit spam costs more than it protects."""
    email = unique_email()
    auth = await signup(client, email=email, password=_PASSWORD, tenant_name="Open Co")
    headers = bearer(auth["access_token"])
    assert (await client.get("/v1/leads", headers=headers)).status_code == 200


async def test_verification_is_idempotent(client, mailer) -> None:
    mailer.sent.clear()
    email = unique_email()
    await signup(client, email=email, password=_PASSWORD, tenant_name="Idem Co")
    token = _token_from_last_email(mailer)

    first = await client.post("/v1/auth/verify-email", json={"token": token})
    second = await client.post("/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 200
    assert second.status_code == 200


async def test_resend_verification_sends_again(client, mailer) -> None:
    email = unique_email()
    auth = await signup(client, email=email, password=_PASSWORD, tenant_name="Resend Co")
    mailer.sent.clear()

    resp = await client.post(
        "/v1/auth/resend-verification", headers=bearer(auth["access_token"])
    )
    assert resp.status_code == 202
    assert len(mailer.sent) == 1
    assert "/verify-email?token=" in mailer.sent[0].body_text
