"""Look up a tenant's API credentials by kind.

Used by the scraping worker to grab the plaintext Serper/Proxycurl
keys at run-time. The caller is responsible for setting the RLS GUC
on the session (the worker does that immediately after opening it).
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.domain.models.credential import Credential
from outreach_os.services import vault_service

log = logging.getLogger(__name__)


async def get_credential_secrets(
    session: AsyncSession, *, tenant_id: uuid.UUID, kinds: list[str]
) -> dict[str, str]:
    """Return a dict of kind -> plaintext secret_payload for the given kinds.

    Decryption happens with the per-tenant DEK. The session MUST have the
    RLS GUC set to `tenant_id` before calling this — the credential table
    is RLS-protected.
    """
    if not kinds:
        return {}
    result = await session.execute(
        select(Credential).where(
            Credential.tenant_id == tenant_id, Credential.kind.in_(kinds)
        )
    )
    out: dict[str, str] = {}
    for cred in result.scalars().all():
        try:
            payload = vault_service.decrypt_for_tenant(str(tenant_id), cred.ciphertext)
        except Exception:  # noqa: BLE001
            log.warning("credential_decrypt_failed", extra={"credential_id": str(cred.id), "kind": cred.kind})
            continue
        # Common conventions: {"api_key": "..."} or {"token": "..."}.
        secret = (
            payload.get("api_key")
            or payload.get("token")
            or payload.get("key")
            or ""
        )
        if secret:
            out[cred.kind] = str(secret)
    return out


async def get_decrypted_credential(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    credential_id: uuid.UUID,
) -> dict[str, str] | None:
    """Decrypt a single credential by id, returning the plaintext payload.

    Returns None if the credential doesn't exist (or RLS hides it).
    The session MUST have the RLS GUC set to `tenant_id` before calling.
    """
    cred = (
        await session.execute(
            select(Credential).where(
                Credential.tenant_id == tenant_id,
                Credential.id == credential_id,
            )
        )
    ).scalar_one_or_none()
    if cred is None:
        return None
    try:
        return vault_service.decrypt_for_tenant(str(tenant_id), cred.ciphertext)
    except Exception:  # noqa: BLE001
        log.warning("credential_decrypt_failed", extra={"credential_id": str(credential_id)})
        return None


async def create_credential(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kind: str,
    plaintext: dict[str, str],
    label: str | None = None,
) -> Credential:
    """Encrypt a dict and store it as a new Credential row.

    Returns the created row. The session must have the RLS GUC set.
    """
    ciphertext = vault_service.encrypt_for_tenant(str(tenant_id), plaintext)
    cred = Credential(
        tenant_id=tenant_id,
        kind=kind,
        ciphertext=ciphertext,
        label=label or kind,
    )
    session.add(cred)
    await session.flush()
    return cred


__all__ = ["create_credential", "get_credential_secrets", "get_decrypted_credential"]
