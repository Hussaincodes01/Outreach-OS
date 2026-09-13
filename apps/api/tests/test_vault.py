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


# --- VAULT_MASTER_KEY missing base64 padding -------------------------------
#
# A 32-byte key base64url-encoded needs exactly one trailing '=' (44 chars);
# some key-generation paths (Node's Buffer.toString("base64url"), a value
# copy-pasted from a source that trims trailing '=') produce the 43-char
# unpadded form instead. Padding only tells the decoder how many bits of the
# final byte group are significant -- it carries no key material -- so the
# padded and unpadded spellings of the same key must decode to identical
# bytes, and both must work as VAULT_MASTER_KEY.

_PADDED_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
_UNPADDED_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
assert len(_UNPADDED_KEY) == 43
assert _PADDED_KEY == _UNPADDED_KEY + "="


def test_unpadded_master_key_roundtrips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_MASTER_KEY", _UNPADDED_KEY)
    ciphertext = vault.encrypt("tenant-a", {"api_key": "sk-test"})
    assert vault.decrypt("tenant-a", ciphertext) == {"api_key": "sk-test"}


def test_unpadded_and_padded_master_key_are_the_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ciphertext produced with the padded key decrypts with the unpadded
    spelling of the same key, proving the two decode to identical bytes."""
    monkeypatch.setenv("VAULT_MASTER_KEY", _PADDED_KEY)
    ciphertext = vault.encrypt("tenant-a", {"api_key": "sk-test"})

    monkeypatch.setenv("VAULT_MASTER_KEY", _UNPADDED_KEY)
    assert vault.decrypt("tenant-a", ciphertext) == {"api_key": "sk-test"}


def test_invalid_base64_master_key_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_MASTER_KEY", "not valid base64!!!")
    with pytest.raises(vault.VaultError, match="base64"):
        vault.encrypt("tenant-a", {"k": "v"})
