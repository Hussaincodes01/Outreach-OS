"""High-level vault API used by services.

Wraps core.vault with a few helpers (encrypt_for_tenant, decrypt_for_tenant)
that accept the same args but are import-stable.
"""
from __future__ import annotations

from typing import Any

from outreach_os.core import vault as _core_vault

encrypt = _core_vault.encrypt
decrypt = _core_vault.decrypt


def encrypt_for_tenant(tenant_id: str, payload: dict[str, Any]) -> bytes:
    return _core_vault.encrypt(tenant_id, payload)


def decrypt_for_tenant(tenant_id: str, ciphertext: bytes) -> dict[str, Any]:
    return _core_vault.decrypt(tenant_id, ciphertext)
