"""Microsoft Graph OAuth."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import jwt

from outreach_os.core.config import get_settings
from outreach_os.core.errors import OAuthError


def _token_url() -> str:
    settings = get_settings()
    return (
        f"https://login.microsoftonline.com/{settings.microsoft_oauth_tenant}"
        f"/oauth2/v2.0/token"
    )


def _auth_url() -> str:
    settings = get_settings()
    return (
        f"https://login.microsoftonline.com/{settings.microsoft_oauth_tenant}"
        f"/oauth2/v2.0/authorize"
    )


def build_state_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, email_hint: str) -> str:
    settings = get_settings()
    payload = {
        "provider": "outlook",
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "email_hint": email_hint,
        "nonce": secrets.token_urlsafe(16),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()),
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_alg
    )


def verify_state_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token, settings.jwt_secret.get_secret_value(), algorithms=[settings.jwt_alg]
        )
    except Exception as exc:
        raise OAuthError(f"invalid OAuth state: {exc}") from exc


def build_auth_url(state: str) -> str:
    settings = get_settings()
    if not settings.microsoft_oauth_client_id:
        raise OAuthError("MICROSOFT_OAUTH_CLIENT_ID is not configured")
    params = {
        "client_id": settings.microsoft_oauth_client_id,
        "response_type": "code",
        "redirect_uri": settings.microsoft_oauth_redirect_uri,
        "response_mode": "query",
        "scope": settings.microsoft_oauth_scopes,
        "state": state,
    }
    return f"{_auth_url()}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.microsoft_oauth_client_id or not settings.microsoft_oauth_client_secret:
        raise OAuthError("Microsoft OAuth is not configured")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _token_url(),
            data={
                "code": code,
                "client_id": settings.microsoft_oauth_client_id,
                "client_secret": settings.microsoft_oauth_client_secret.get_secret_value(),
                "redirect_uri": settings.microsoft_oauth_redirect_uri,
                "grant_type": "authorization_code",
                "scope": settings.microsoft_oauth_scopes,
            },
        )
    if resp.status_code != 200:
        raise OAuthError(
            f"Microsoft token exchange failed: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()
