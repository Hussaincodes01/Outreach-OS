"""Vault tests — per-tenant DEK derivation and decrypt-on-wrong-tenant failure."""
from __future__ import annotations

import pytest

from outreach_os.core import vault


def test_encrypt_decrypt_roundtrip() -> None:
    ciphertext = vault.encrypt("tenant-a", {"api_key": "sk-test"})
    plaintext = vault.decrypt("tenant-a", ciphertext)
    assert plaintext == {"api_key": "sk-test"}


def test_decrypt_with_wrong_tenant_fails() -> None:
    ciphertext = vault.encrypt("tenant-a", {"api_key": "sk-test"})
    with pytest.raises(vault.VaultError):
        vault.decrypt("tenant-b", ciphertext)


def test_different_tenants_produce_different_ciphertexts() -> None:
    a = vault.encrypt("tenant-a", {"k": "v"})
    b = vault.encrypt("tenant-b", {"k": "v"})
    assert a != b


def test_empty_payload_roundtrip() -> None:
    ciphertext = vault.encrypt("t", {})
    assert vault.decrypt("t", ciphertext) == {}


def test_tampered_ciphertext_fails() -> None:
    ciphertext = vault.encrypt("t", {"k": "v"})
    bad = bytearray(ciphertext)
    bad[10] ^= 0xFF
    with pytest.raises(vault.VaultError):
        vault.decrypt("t", bytes(bad))


def test_unicode_payload() -> None:
    payload = {"name": "株式会社", "emoji": "🔐"}
    ciphertext = vault.encrypt("t", payload)
    assert vault.decrypt("t", ciphertext) == payload
