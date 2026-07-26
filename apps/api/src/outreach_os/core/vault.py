"""Per-tenant DEK wrapped by a master KEK.

Plaintext secrets (LLM keys, OAuth refresh tokens, SMTP passwords) are
encrypted with a tenant-specific Data Encryption Key (DEK) derived from
the master Key Encryption Key (KEK) via SHA-256(KEK || tenant_id).

This is appropriate for v1. For enterprise v2, swap the master KEK
storage to AWS KMS / GCP KMS / HashiCorp Vault and use envelope
encryption (GenerateDataKey + Encrypt) so the master key never lives
in env.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, cast

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    pass


def _master_kek() -> bytes:
    raw = os.environ.get("VAULT_MASTER_KEY", "")
    if not raw:
        raise VaultError("VAULT_MASTER_KEY is not set")
    try:
        decoded = base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise VaultError("VAULT_MASTER_KEY must be base64-encoded") from exc
    if len(decoded) < 16:
        raise VaultError("VAULT_MASTER_KEY must decode to at least 16 bytes")
    return decoded


def _dek_for_tenant(tenant_id: str) -> bytes:
    """Derive a per-tenant DEK as base64(SHA256(KEK || tenant_id))."""
    if not tenant_id:
        raise VaultError("tenant_id required to derive DEK")
    digest = hashlib.sha256(_master_kek() + tenant_id.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet(tenant_id: str) -> Fernet:
    return Fernet(_dek_for_tenant(tenant_id))


def encrypt(tenant_id: str, plaintext: dict[str, Any]) -> bytes:
    """Encrypt a JSON-serialisable dict for the given tenant."""
    try:
        payload = json.dumps(plaintext, separators=(",", ":")).encode("utf-8")
        return _fernet(tenant_id).encrypt(payload)
    except (TypeError, ValueError) as exc:
        raise VaultError(f"plaintext not JSON-serialisable: {exc}") from exc


def decrypt(tenant_id: str, ciphertext: bytes) -> dict[str, Any]:
    """Decrypt ciphertext for the given tenant. Raises VaultError on failure."""
    try:
        plaintext = _fernet(tenant_id).decrypt(ciphertext)
    except InvalidToken as exc:
        raise VaultError("invalid ciphertext (wrong tenant or tampered data)") from exc
    try:
        return cast("dict[str, Any]", json.loads(plaintext))
    except (TypeError, ValueError) as exc:
        raise VaultError("decrypted payload is not valid JSON") from exc
