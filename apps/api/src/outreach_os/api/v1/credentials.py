"""Credential endpoints — encrypted secrets the customer provides to us."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.vault import VaultError
from outreach_os.domain.models.credential import Credential
from outreach_os.domain.schemas.credential import (
    CredentialCreate,
    CredentialOut,
    CredentialTestResult,
)
from outreach_os.services import vault_service

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("", response_model=list[CredentialOut])
async def list_credentials(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[CredentialOut]:
    result = await db.execute(
        select(Credential).order_by(Credential.created_at.desc())
    )
    return [
        CredentialOut(
            id=c.id,
            kind=c.kind,
            label=c.label,
            created_at=c.created_at,
            last_used_at=c.last_used_at,
            has_secret=True,
        )
        for c in result.scalars().all()
    ]


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(
    payload: CredentialCreate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CredentialOut:
    if user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
        )
    try:
        ciphertext = vault_service.encrypt_for_tenant(
            str(user.tenant_id), payload.secret_payload
        )
    except VaultError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"vault error: {exc}",
        ) from exc

    cred = Credential(
        tenant_id=user.tenant_id,
        kind=payload.kind,
        label=payload.label,
        ciphertext=ciphertext,
        created_by=user.user_id,
    )
    db.add(cred)
    await db.flush()

    await write_audit_event(
        db,
        action="credential.created",
        target_type="credential",
        target_id=cred.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"kind": cred.kind, "label": cred.label},
    )
    return CredentialOut(
        id=cred.id,
        kind=cred.kind,
        label=cred.label,
        created_at=cred.created_at,
        last_used_at=cred.last_used_at,
        has_secret=True,
    )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    cred = await db.get(Credential, credential_id)
    if cred is None:
        # 404, not 403 — never reveal existence across tenants.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="credential not found"
        )
    await db.delete(cred)
    await write_audit_event(
        db,
        action="credential.deleted",
        target_type="credential",
        target_id=credential_id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"kind": cred.kind, "label": cred.label},
    )


@router.post("/{credential_id}/test", response_model=CredentialTestResult)
async def test_credential(
    credential_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> CredentialTestResult:
    """Decrypt and validate the secret shape. For Phase 0+1 we just check
    that decrypt succeeds. Phase 3 will add provider-specific liveness
    (e.g. a cheap list-models call to OpenAI)."""
    cred = await db.get(Credential, credential_id)
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="credential not found"
        )
    try:
        vault_service.decrypt_for_tenant(str(user.tenant_id), cred.ciphertext)
    except VaultError as exc:
        return CredentialTestResult(ok=False, message=str(exc))
    return CredentialTestResult(ok=True, message="decryption ok")
