"""Gmail OAuth — build auth URL, exchange code, persist refresh token.

Uses Google Identity Services (OAuth 2.0 authorization code with PKCE-lite;
we use a server-stored `state` JWT instead of PKCE because the state is
single-use and tied to the authenticated user, which is sufficient for
our threat model. For production-grade, switch to PKCE.
"""
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


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def build_state_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    settings = get_settings()
    payload = {
        "provider": "gmail",
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
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
    if not settings.google_oauth_client_id:
        raise OAuthError("GOOGLE_OAUTH_CLIENT_ID is not configured")
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": settings.google_oauth_scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise OAuthError("Google OAuth is not configured")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret.get_secret_value(),
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        raise OAuthError(
            f"Google token exchange failed: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()


def extract_email_and_refresh(tokens: dict[str, Any]) -> tuple[str, str | None]:
    email = tokens.get("id_token_claims_email") or tokens.get("email")
    if not email:
        # Decoding the id_token is required to get the email; left as a TODO
        # for v2. For v1, the user supplies the address during the flow
        # (passed in the state) — handled by the API layer.
        raise OAuthError("Google response missing email; pass it explicitly")
    return email, tokens.get("refresh_token")
