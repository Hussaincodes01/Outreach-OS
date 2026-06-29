"""Password hashing + JWT issuance/verification with key rotation.

We use passlib[bcrypt] for passwords and python-jose for JWTs. The access
TTL is short (15 min); the refresh TTL is longer (30 days). Both are HS256
signed with JWT_SECRET. Supports key rotation via `jwt_secret_keys` (JSON
dict of kid->secret). The active key is `jwt_active_key_id` (default "1").
For multi-issuer setups, swap to RS256 + JWKS.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from outreach_os.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_active_secret() -> str:
    """Return the active JWT signing secret (supports rotation)."""
    settings = get_settings()
    # Check for rotation config first
    if settings.jwt_secret_keys:
        try:
            keys = json.loads(settings.jwt_secret_keys.get_secret_value())
            active_kid = settings.jwt_active_key_id or "1"
            return keys.get(active_kid, settings.jwt_secret.get_secret_value())
        except Exception:
            pass
    return settings.jwt_secret.get_secret_value()


def _get_all_secrets() -> list[str]:
    """Return all valid secrets for verification (supports rotation)."""
    settings = get_settings()
    secrets_list = [settings.jwt_secret.get_secret_value()]
    if settings.jwt_secret_keys:
        try:
            keys = json.loads(settings.jwt_secret_keys.get_secret_value())
            secrets_list.extend(keys.values())
        except Exception:
            pass
    # Deduplicate while preserving order
    seen = set()
    return [s for s in secrets_list if not (s in seen or seen.add(s))]


def _build_token(
    *,
    sub: str,
    tenant_id: str,
    token_type: str,
    ttl: timedelta,
    extra: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    iat = _now()
    payload: dict[str, Any] = {
        "sub": sub,
        "tid": tenant_id,
        "typ": token_type,
        "iat": int(iat.timestamp()),
        "exp": int((iat + ttl).timestamp()),
        "jti": str(uuid.uuid4()),
        "kid": settings.jwt_active_key_id or "1",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(
        payload,
        _get_active_secret(),
        algorithm=settings.jwt_alg,
    )


def create_access_token(*, user_id: str, tenant_id: str, role: str = "member") -> str:
    settings = get_settings()
    return _build_token(
        sub=user_id,
        tenant_id=tenant_id,
        token_type="access",
        ttl=timedelta(minutes=settings.jwt_access_ttl_minutes),
        extra={"role": role},
    )


def create_refresh_token(*, user_id: str, tenant_id: str, role: str = "member") -> str:
    settings = get_settings()
    return _build_token(
        sub=user_id,
        tenant_id=tenant_id,
        token_type="refresh",
        ttl=timedelta(days=settings.jwt_refresh_ttl_days),
        extra={"role": role},
    )


class TokenError(Exception):
    pass


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    last_exc = None
    for secret in _get_all_secrets():
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[settings.jwt_alg],
            )
            break
        except JWTError as exc:
            last_exc = exc
            continue
    else:
        raise TokenError(f"invalid token: {last_exc}") from last_exc

    if payload.get("typ") != expected_type:
        raise TokenError(f"expected {expected_type} token, got {payload.get('typ')}")
    if not payload.get("sub") or not payload.get("tid"):
        raise TokenError("token missing required claims")
    return payload


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
