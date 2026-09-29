"""Password hashing + JWT issuance/verification with key rotation.

We use passlib[bcrypt] for passwords and python-jose for JWTs. The access
TTL is short (15 min); the refresh TTL is longer (30 days). Both are HS256
signed with JWT_SECRET. Supports key rotation via `jwt_secret_keys` (JSON
dict of kid->secret). The active key is `jwt_active_key_id` (default "1").
For multi-issuer setups, swap to RS256 + JWKS.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from jose import JWTError, jwt
from passlib.context import CryptContext

from outreach_os.core.config import get_settings

log = logging.getLogger(__name__)

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
            return cast("str", keys.get(active_kid, settings.jwt_secret.get_secret_value()))
        except Exception:
            # Malformed JWT_SECRET_KEYS: fall back to the single secret rather
            # than failing every request, but make it visible in the logs.
            log.warning("JWT_SECRET_KEYS is not valid JSON; using JWT_SECRET", exc_info=True)
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
            # Same as above: verification still works against JWT_SECRET.
            log.warning("JWT_SECRET_KEYS is not valid JSON; using JWT_SECRET", exc_info=True)
    # Deduplicate while preserving order.
    return list(dict.fromkeys(secrets_list))


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
    return cast(
        "str",
        jwt.encode(
            payload,
            _get_active_secret(),
            algorithm=settings.jwt_alg,
        ),
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
    return cast("dict[str, Any]", payload)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


# --- Single-purpose action tokens ------------------------------------------


def _password_fingerprint(password_hash: str) -> str:
    """Short digest of the stored hash, embedded in reset tokens.

    This is what makes a reset link single-use without a database table:
    completing a reset changes the password hash, so the fingerprint no longer
    matches and the same link cannot be replayed. It also invalidates
    outstanding links whenever the password changes by any route.

    The hash itself is never exposed — only a truncated SHA-256 of it.
    """
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_password_reset_token(
    *, user_id: str, tenant_id: str, password_hash: str
) -> str:
    settings = get_settings()
    return _build_token(
        sub=user_id,
        tenant_id=tenant_id,
        token_type="password_reset",
        ttl=timedelta(minutes=settings.password_reset_ttl_minutes),
        extra={"pfp": _password_fingerprint(password_hash)},
    )


def decode_password_reset_token(token: str, *, password_hash: str) -> dict[str, Any]:
    """Decode a reset token and reject it if the password already changed."""
    claims = decode_token(token, expected_type="password_reset")
    if claims.get("pfp") != _password_fingerprint(password_hash):
        raise TokenError("this reset link has already been used or has expired")
    return claims


def create_email_verification_token(*, user_id: str, tenant_id: str, email: str) -> str:
    settings = get_settings()
    return _build_token(
        sub=user_id,
        tenant_id=tenant_id,
        token_type="email_verify",
        ttl=timedelta(hours=settings.email_verification_ttl_hours),
        # Binding the address stops a link issued for one email from verifying
        # a different one after an address change.
        extra={"eml": email.lower()},
    )


def decode_email_verification_token(token: str, *, email: str) -> dict[str, Any]:
    claims = decode_token(token, expected_type="email_verify")
    if str(claims.get("eml", "")).lower() != email.lower():
        raise TokenError("this verification link was issued for a different address")
    return claims
