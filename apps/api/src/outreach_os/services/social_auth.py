"""Sign in with Google / Microsoft.

Deliberately thin. We do NOT implement OIDC token validation, JWKS fetching or
key rotation — after exchanging the authorization code we ask the provider who
the user is via their own OpenID Connect `userinfo` endpoint, over TLS, using
the access token we just received. That is a documented, supported call, and it
keeps identity verification inside the provider rather than in code we would
have to keep correct forever.

Reuses the OAuth client credentials already configured for mailbox connection,
with their own redirect URIs so the two flows stay separate: connecting a
mailbox asks for send/read scopes, signing in asks only for identity.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from jose import jwt

from outreach_os.core.config import get_settings
from outreach_os.core.errors import OAuthError

# Identity only. No mail scopes: signing in must never grant us the ability to
# read or send a user's email.
_IDENTITY_SCOPES = "openid email profile"

_STATE_TTL_MINUTES = 10


@dataclass(frozen=True)
class SocialProvider:
    key: str
    label: str
    authorize_url: str
    token_url: str
    userinfo_url: str


def _microsoft_tenant() -> str:
    return get_settings().microsoft_oauth_tenant or "common"


def providers() -> dict[str, SocialProvider]:
    tenant = _microsoft_tenant()
    return {
        "google": SocialProvider(
            key="google",
            label="Google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        ),
        "microsoft": SocialProvider(
            key="microsoft",
            label="Microsoft",
            authorize_url=(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
            ),
            token_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            userinfo_url="https://graph.microsoft.com/oidc/userinfo",
        ),
    }


def get_provider(key: str) -> SocialProvider:
    provider = providers().get(key)
    if provider is None:
        raise OAuthError(f"unsupported sign-in provider {key!r}")
    return provider


def _credentials(key: str) -> tuple[str, str, str]:
    """(client_id, client_secret, redirect_uri) for a provider."""
    settings = get_settings()
    if key == "google":
        client_id = settings.google_oauth_client_id
        secret = settings.google_oauth_client_secret.get_secret_value()
        redirect = settings.google_login_redirect_uri
    else:
        client_id = settings.microsoft_oauth_client_id
        secret = settings.microsoft_oauth_client_secret.get_secret_value()
        redirect = settings.microsoft_login_redirect_uri
    if not client_id or not secret:
        raise OAuthError(
            f"{get_provider(key).label} sign-in is not configured on this server"
        )
    return client_id, secret, redirect


def configured_providers() -> list[dict[str, str]]:
    """Providers this deployment can actually use.

    The login page reads this so it never shows a button that would fail —
    an operator who hasn't set up Microsoft shouldn't advertise it.
    """
    settings = get_settings()
    out: list[dict[str, str]] = []
    if settings.google_oauth_client_id and settings.google_oauth_client_secret:
        out.append({"provider": "google", "label": "Google"})
    if settings.microsoft_oauth_client_id and settings.microsoft_oauth_client_secret:
        out.append({"provider": "microsoft", "label": "Microsoft"})
    return out


def build_state(*, provider: str, invite_tenant_slug: str | None = None) -> str:
    """Signed, short-lived, single-purpose state.

    Carries a nonce so a replayed callback is bounded by the TTL, and the
    provider so a state minted for one cannot be presented to another.
    """
    settings = get_settings()
    payload: dict[str, Any] = {
        "typ": "social_login_state",
        "provider": provider,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(
            (
                datetime.now(timezone.utc) + timedelta(minutes=_STATE_TTL_MINUTES)
            ).timestamp()
        ),
    }
    if invite_tenant_slug:
        payload["slug"] = invite_tenant_slug
    return cast(
        "str",
        jwt.encode(
            payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_alg
        ),
    )


def verify_state(token: str, *, provider: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims = cast(
            "dict[str, Any]",
            jwt.decode(
                token,
                settings.jwt_secret.get_secret_value(),
                algorithms=[settings.jwt_alg],
            ),
        )
    except Exception as exc:
        raise OAuthError("sign-in link expired or invalid, please try again") from exc
    if claims.get("typ") != "social_login_state":
        raise OAuthError("invalid sign-in state")
    if claims.get("provider") != provider:
        raise OAuthError("sign-in state does not match this provider")
    return claims


def build_authorize_url(key: str, state: str) -> str:
    provider = get_provider(key)
    client_id, _secret, redirect = _credentials(key)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": _IDENTITY_SCOPES,
        "state": state,
        # Force the account chooser: shared machines otherwise silently sign
        # the previous person back in.
        "prompt": "select_account",
    }
    return f"{provider.authorize_url}?{urlencode(params)}"


@dataclass(frozen=True)
class SocialIdentity:
    email: str
    full_name: str | None
    provider: str
    # Provider's stable user id. Emails can be reassigned inside a workspace;
    # this cannot.
    subject: str
    email_verified: bool


async def exchange_and_identify(key: str, code: str) -> SocialIdentity:
    """Swap the authorization code for tokens, then ask who this is."""
    provider = get_provider(key)
    client_id, client_secret, redirect = _credentials(key)

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            provider.token_url,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise OAuthError(
                f"{provider.label} rejected the sign-in: {token_resp.status_code}"
            )
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise OAuthError(f"{provider.label} returned no access token")

        # The provider is the authority on identity — we never parse or verify
        # an id_token ourselves.
        info_resp = await client.get(
            provider.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if info_resp.status_code != 200:
        raise OAuthError(f"could not read your {provider.label} profile")

    info: dict[str, Any] = info_resp.json()
    email = str(info.get("email") or "").strip().lower()
    if not email:
        raise OAuthError(
            f"Your {provider.label} account has no email address available. "
            "Sign in with a password instead."
        )
    subject = str(info.get("sub") or info.get("oid") or email)
    # Google reports this explicitly; Microsoft work accounts are verified by
    # virtue of being directory-issued.
    verified = bool(info.get("email_verified", True))
    name = info.get("name") or info.get("displayName")
    return SocialIdentity(
        email=email,
        full_name=str(name) if name else None,
        provider=key,
        subject=subject,
        email_verified=verified,
    )


__all__ = [
    "SocialIdentity",
    "SocialProvider",
    "build_authorize_url",
    "build_state",
    "configured_providers",
    "exchange_and_identify",
    "get_provider",
    "providers",
    "verify_state",
]
