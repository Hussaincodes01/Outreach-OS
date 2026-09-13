"""Credential endpoints — encrypted secrets the customer provides to us."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.env_keys import provider_base_var, provider_key_var, scraping_key_var
from outreach_os.core.vault import VaultError
from outreach_os.domain.models.credential import Credential
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.schemas.credential import (
    CredentialCreate,
    CredentialOut,
    CredentialTestResult,
    ProviderOut,
    ProviderTestOut,
    ScrapingKeyOut,
)
from outreach_os.services import vault_service
from outreach_os.services.credential_lookup import get_credential_secrets
from outreach_os.services.llm_credentials import (
    NON_LLM_KINDS,
    PROVIDERS,
    VALID_CREDENTIAL_KINDS,
    MissingLLMCredentialsError,
    env_credentials,
    provider_spec,
    spec_for_kind,
    verify_credentials,
)

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
    if payload.kind not in VALID_CREDENTIAL_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"unknown credential kind {payload.kind!r}; "
                f"expected one of: {', '.join(sorted(VALID_CREDENTIAL_KINDS))}"
            ),
        )
    spec = spec_for_kind(payload.kind)
    has_key = any(payload.secret_payload.get(k) for k in ("api_key", "key", "token"))
    # Self-hosted providers (Ollama) authenticate by network reachability, not
    # a key, so requiring one would make them impossible to connect.
    needs_key = spec.requires_api_key if spec else True
    if needs_key and not has_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="secret_payload must contain a non-empty 'api_key'",
        )
    if spec and spec.requires_api_base and not payload.secret_payload.get("api_base"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{spec.label} needs an 'api_base' URL in secret_payload"
                f"{f' (e.g. {spec.api_base_hint})' if spec.api_base_hint else ''}"
            ),
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
    """Verify a stored credential.

    For LLM providers this makes one real, 1-token call so the answer means
    "the provider accepts this key", not merely "we could decrypt it". A user
    clicking Test wants the former.
    """
    cred = await db.get(Credential, credential_id)
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="credential not found"
        )
    try:
        vault_service.decrypt_for_tenant(str(user.tenant_id), cred.ciphertext)
    except VaultError as exc:
        return CredentialTestResult(ok=False, message=str(exc))

    spec = spec_for_kind(cred.kind)
    if spec is None:
        # Non-LLM integration (Serper, Proxycurl, ...): no cheap universal
        # probe, so decryption is the strongest claim we can honestly make.
        return CredentialTestResult(
            ok=True, message="stored and decryptable", verified_live=False
        )

    # Pass the row explicitly: a workspace may hold several keys for one
    # provider, and Test must report on the one the user clicked.
    ok, message = await verify_credentials(
        db, tenant_id=user.tenant_id, provider=spec.provider, credential=cred
    )
    # Only a provider we can probe yields a live result. For a gateway endpoint
    # there is no universal model to call, so saying "verified" would claim
    # more than we did.
    live = spec.verify_model is not None
    if ok and live:
        cred.last_verified_at = datetime.now(timezone.utc)
        await db.flush()
    return CredentialTestResult(ok=ok, message=message, verified_live=live)


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[ProviderOut]:
    """Every connectable LLM provider, and whether this tenant has wired it up.

    The integrations page and the onboarding checklist both read this, so the
    UI never hard-codes a provider list that can drift from the backend.

    An env-configured provider (see `core.env_keys`) always reports as
    connected, ahead of any stored row for the same provider.
    """
    rows = (await db.execute(select(Credential))).scalars().all()
    by_kind = {c.kind: c for c in rows}
    tenant = await db.get(Tenant, user.tenant_id)
    verified_providers: dict[str, str] = (
        (tenant.onboarding_state or {}).get("verified_providers", {}) if tenant else {}
    )

    out: list[ProviderOut] = []
    for p in PROVIDERS:
        stored = by_kind.get(p.credential_kind)
        configured_via: Literal["env", "stored"] | None
        if env_credentials(p.provider) is not None:
            connected = True
            configured_via = "env"
            verified_at_raw = verified_providers.get(p.provider)
            last_verified_at = (
                datetime.fromisoformat(verified_at_raw) if verified_at_raw else None
            )
        elif stored is not None:
            connected = True
            configured_via = "stored"
            last_verified_at = stored.last_verified_at
        else:
            connected = False
            configured_via = None
            last_verified_at = None

        out.append(
            ProviderOut(
                provider=p.provider,
                credential_kind=p.credential_kind,
                label=p.label,
                console_url=p.console_url,
                supports_embeddings=p.supports_embeddings,
                connected=connected,
                last_verified_at=last_verified_at,
                description=p.description,
                requires_api_base=p.requires_api_base,
                requires_api_key=p.requires_api_key,
                api_base_hint=p.api_base_hint,
                model_count=len(p.models),
                allows_custom_model=p.allows_custom_model,
                env_var=provider_key_var(p.provider),
                env_base_var=provider_base_var(p.provider),
                configured_via=configured_via,
            )
        )
    return out


@router.post("/providers/{provider}/test", response_model=ProviderTestOut)
async def test_provider(
    provider: str,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> ProviderTestOut:
    """Verify whichever key is active for `provider` — env first, else stored.

    Reuses `verify_credentials` (the same probe the stored-credential Test
    button uses) rather than re-implementing the live call: `load_credentials`
    already applies the env-first precedence, so this one probe covers both
    sources.
    """
    spec = provider_spec(provider)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown provider {provider!r}"
        )

    if env_credentials(provider) is None:
        stored = (
            await db.execute(
                select(Credential)
                .where(
                    Credential.tenant_id == user.tenant_id,
                    Credential.kind == spec.credential_kind,
                )
                .order_by(Credential.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if stored is None:
            raise MissingLLMCredentialsError(provider)

    ok, message = await verify_credentials(db, tenant_id=user.tenant_id, provider=provider)
    # Only a provider we can probe yields a live result. For a gateway endpoint
    # there is no universal model to call, so saying "verified" would claim
    # more than we did — mirrors the stored-credential Test endpoint above.
    live = spec.verify_model is not None
    if ok and live:
        tenant = await db.get(Tenant, user.tenant_id)
        if tenant is not None:
            # Reassign (rather than mutate in place) so SQLAlchemy detects the
            # JSONB change and flushes it.
            state = dict(tenant.onboarding_state or {})
            verified = dict(state.get("verified_providers") or {})
            verified[provider] = datetime.now(timezone.utc).isoformat()
            state["verified_providers"] = verified
            tenant.onboarding_state = state
            await db.flush()
        await write_audit_event(
            db,
            action="credential.provider.verified",
            target_type="credential",
            actor_kind="user",
            actor_id=user.user_id,
            payload={"provider": provider},
        )
    return ProviderTestOut(ok=ok, message=message)


@router.get("/scraping", response_model=list[ScrapingKeyOut])
async def list_scraping_keys(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[ScrapingKeyOut]:
    """Every non-LLM integration kind and whether a secret (env or stored) is
    available for it."""
    secrets = await get_credential_secrets(
        db, tenant_id=user.tenant_id, kinds=list(NON_LLM_KINDS)
    )
    return [
        ScrapingKeyOut(
            kind=kind,
            env_var=scraping_key_var(kind),
            configured=kind in secrets,
        )
        for kind in NON_LLM_KINDS
    ]
