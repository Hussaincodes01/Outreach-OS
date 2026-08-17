"""Sign in with Google / Microsoft.

The linking rules are the security surface here. An identity provider asserts
"this is dana@acme.com"; if we trust that assertion when the provider itself
hasn't verified the address, anyone who can register that address at any
configured provider inherits the matching workspace.
"""
from __future__ import annotations

import uuid

import pytest

from outreach_os.core.db import session_scope
from outreach_os.core.errors import AuthError, OAuthError
from outreach_os.services import social_auth
from outreach_os.services.social_auth import SocialIdentity
from outreach_os.services.social_login_service import sign_in_or_provision
from tests.conftest import signup, unique_email

pytestmark = pytest.mark.asyncio


def _identity(
    email: str,
    *,
    provider: str = "google",
    subject: str | None = None,
    verified: bool = True,
    name: str | None = "Dana Reeves",
) -> SocialIdentity:
    return SocialIdentity(
        email=email,
        full_name=name,
        provider=provider,
        subject=subject or f"sub-{uuid.uuid4().hex[:12]}",
        email_verified=verified,
    )


# --- state token ------------------------------------------------------------


async def test_state_is_bound_to_one_provider() -> None:
    """A state minted for Google must not be presentable to Microsoft."""
    state = social_auth.build_state(provider="google")
    social_auth.verify_state(state, provider="google")
    with pytest.raises(OAuthError, match="does not match"):
        social_auth.verify_state(state, provider="microsoft")


async def test_garbage_state_is_refused() -> None:
    with pytest.raises(OAuthError):
        social_auth.verify_state("not-a-token", provider="google")


async def test_unknown_provider_is_refused() -> None:
    with pytest.raises(OAuthError, match="unsupported"):
        social_auth.get_provider("facebook")


async def test_sign_in_requests_identity_scopes_only() -> None:
    """Signing in must never ask for permission to read or send mail.

    Asserted on the constant rather than a built URL: the scope set is the
    property that matters, and it holds regardless of whether this deployment
    has OAuth credentials configured.
    """
    scopes = set(social_auth._IDENTITY_SCOPES.split())
    assert scopes == {"openid", "email", "profile"}
    joined = social_auth._IDENTITY_SCOPES
    for mail_scope in ("gmail", "mail.send", "mail.read", "https://"):
        assert mail_scope not in joined


async def test_sign_in_and_mailbox_flows_use_different_callbacks() -> None:
    """Separate redirect URIs mean an authorization code minted for signing in
    cannot be redeemed against the mailbox flow, which asks for mail scopes."""
    from outreach_os.core.config import get_settings

    settings = get_settings()
    assert settings.google_login_redirect_uri != settings.google_oauth_redirect_uri
    assert (
        settings.microsoft_login_redirect_uri != settings.microsoft_oauth_redirect_uri
    )


async def test_only_configured_providers_are_advertised(client) -> None:
    """A button that dead-ends is worse than no button."""
    resp = await client.get("/v1/auth/oauth/providers")
    assert resp.status_code == 200
    # Nothing is configured in the test environment.
    assert resp.json() == []


# --- provisioning and linking ----------------------------------------------


async def test_first_sign_in_provisions_a_workspace(client) -> None:
    identity = _identity(unique_email())
    async with session_scope() as session:
        user, created = await sign_in_or_provision(session, identity)
        assert created is True
        assert user.role == "owner"
        assert user.auth_provider == "google"
        assert user.auth_subject == identity.subject
        # The provider already confirmed the address.
        assert user.email_verified_at is not None


async def test_returning_user_is_matched_on_subject_not_email(client) -> None:
    """Email can be reassigned inside a company; the subject cannot."""
    identity = _identity(unique_email())
    async with session_scope() as session:
        first, created_first = await sign_in_or_provision(session, identity)
        first_id = first.id

    renamed = SocialIdentity(
        email=unique_email(),  # same person, new address
        full_name=identity.full_name,
        provider=identity.provider,
        subject=identity.subject,
        email_verified=True,
    )
    async with session_scope() as session:
        second, created_second = await sign_in_or_provision(session, renamed)
        assert created_first is True
        assert created_second is False
        assert second.id == first_id


async def test_verified_social_email_links_to_an_existing_password_account(
    client,
) -> None:
    """Someone who signed up with a password then clicks "Sign in with Google"
    should land in their own workspace, not a fresh empty one."""
    email = unique_email()
    auth = await signup(
        client,
        email=email,
        password="correct-horse-battery-staple",
        tenant_name="Existing Co",
    )
    async with session_scope() as session:
        user, created = await sign_in_or_provision(session, _identity(email))
        assert created is False
        assert str(user.tenant_id) == auth["tenant_id"]
        assert user.auth_provider == "google"


async def test_unverified_social_email_will_not_link(client) -> None:
    """The takeover path: refuse rather than link when the provider won't
    vouch for the address."""
    email = unique_email()
    await signup(
        client,
        email=email,
        password="correct-horse-battery-staple",
        tenant_name="Target Co",
    )
    async with session_scope() as session:
        with pytest.raises(AuthError, match="not verified"):
            await sign_in_or_provision(session, _identity(email, verified=False))


async def test_deactivated_accounts_cannot_sign_in_socially(client) -> None:
    email = unique_email()
    identity = _identity(email)
    async with session_scope() as session:
        user, _ = await sign_in_or_provision(session, identity)
        user.is_active = False
        await session.flush()

    async with session_scope() as session:
        with pytest.raises(AuthError, match="deactivated"):
            await sign_in_or_provision(session, identity)


async def test_sso_users_cannot_sign_in_with_a_password(client) -> None:
    """SSO accounts get an unusable hash, so the password path must reject
    them rather than accept an empty or guessable secret."""
    email = unique_email()
    async with session_scope() as session:
        await sign_in_or_provision(session, _identity(email))

    for attempt in ("", "password", "correct-horse-battery-staple"):
        resp = await client.post(
            "/v1/auth/login", json={"email": email, "password": attempt or "x" * 12}
        )
        assert resp.status_code == 401, attempt


async def test_workspace_is_named_after_the_company_domain(client) -> None:
    async with session_scope() as session:
        user, _ = await sign_in_or_provision(
            session, _identity(f"dana-{uuid.uuid4().hex[:8]}@northwind-labs.example")
        )
        from outreach_os.domain.models.tenant import Tenant

        tenant = await session.get(Tenant, user.tenant_id)
        assert tenant is not None
        assert tenant.name == "Northwind Labs"


async def test_consumer_addresses_do_not_become_the_workspace_name(client) -> None:
    """"Gmail" would be a terrible workspace name."""
    async with session_scope() as session:
        user, _ = await sign_in_or_provision(
            session, _identity(f"dana-{uuid.uuid4().hex[:8]}@gmail.com")
        )
        from outreach_os.domain.models.tenant import Tenant

        tenant = await session.get(Tenant, user.tenant_id)
        assert tenant is not None
        assert "Gmail" not in tenant.name
        assert "Dana Reeves" in tenant.name


# --- endpoints --------------------------------------------------------------


async def test_start_is_refused_when_provider_is_unconfigured(client) -> None:
    resp = await client.get("/v1/auth/oauth/google/start", follow_redirects=False)
    assert resp.status_code == 400
    assert "not configured" in resp.json()["detail"]


async def test_callback_redirects_home_on_provider_error(client) -> None:
    """A cancelled consent screen is a normal outcome, not a 500."""
    resp = await client.get(
        "/v1/auth/oauth/google/callback?error=access_denied", follow_redirects=False
    )
    assert resp.status_code == 307
    assert "/login?error=" in resp.headers["location"]


async def test_callback_without_a_code_redirects_rather_than_erroring(client) -> None:
    resp = await client.get(
        "/v1/auth/oauth/google/callback", follow_redirects=False
    )
    assert resp.status_code == 307
    assert "/login?error=" in resp.headers["location"]
