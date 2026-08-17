"""Onboarding + workspace LLM settings.

Two things a self-serve user needs that the rest of the API doesn't provide:
a truthful "what's left to set up?" checklist, and a place to choose which
model their own key should drive.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.domain.models.credential import Credential
from outreach_os.domain.models.knowledge_base_chunk import EMBEDDING_DIM
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.schemas.onboarding import (
    EmbeddingModelOut,
    LlmSettingsIn,
    LlmSettingsOut,
    ModelOut,
    OnboardingDismissIn,
    OnboardingStatusOut,
    OnboardingStepOut,
)
from outreach_os.services import onboarding_service
from outreach_os.services.llm_credentials import (
    PROVIDERS,
    UnknownProviderError,
    chat_models,
    embedding_spec,
    load_credentials,
    provider_for_model,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingStatusOut)
async def get_onboarding(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> OnboardingStatusOut:
    """The setup checklist, derived from live state on every call."""
    status_ = await onboarding_service.get_status(db, tenant_id=user.tenant_id)
    if status_.ready:
        await onboarding_service.mark_completed(db, tenant_id=user.tenant_id)
    nxt = status_.next_step
    return OnboardingStatusOut(
        ready=status_.ready,
        dismissed=status_.dismissed,
        completed_at=status_.completed_at,
        next_step_key=nxt.key if nxt else None,
        steps=[
            OnboardingStepOut(
                key=s.key,
                title=s.title,
                description=s.description,
                done=s.done,
                required=s.required,
                href=s.href,
                detail=s.detail,
            )
            for s in status_.steps
        ],
    )


@router.post("/dismiss", response_model=OnboardingStatusOut)
async def dismiss_onboarding(
    body: OnboardingDismissIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> OnboardingStatusOut:
    await onboarding_service.set_dismissed(
        db, tenant_id=user.tenant_id, dismissed=body.dismissed
    )
    return await get_onboarding(user=user, db=db)


async def _connected_providers(
    db: AsyncSession, tenant_id: uuid.UUID
) -> set[str]:
    """Which providers this tenant actually has a usable credential for."""
    rows = (await db.execute(select(Credential.kind))).scalars().all()
    kinds = set(rows)
    return {p.provider for p in PROVIDERS if p.credential_kind in kinds}


async def _settings_payload(db: AsyncSession, tenant: Tenant) -> LlmSettingsOut:
    connected = await _connected_providers(db, tenant.id)
    return LlmSettingsOut(
        default_llm_model=tenant.default_llm_model,
        embedding_llm_model=tenant.embedding_llm_model,
        available_models=[m.id for m in chat_models()],
        models=[
            ModelOut(
                id=m.id,
                label=m.label,
                provider=p.provider,
                provider_label=p.label,
                supports_tools=m.supports_tools,
                context_window=m.context_window,
                tier=m.tier,
                available=p.provider in connected,
            )
            for p in PROVIDERS
            for m in p.models
        ],
        custom_model_providers=[
            p.provider
            for p in PROVIDERS
            if p.allows_custom_model and p.provider in connected
        ],
        embedding_models=[
            EmbeddingModelOut(
                id=e.id,
                label=e.label,
                provider=p.provider,
                provider_label=p.label,
                dimensions=e.dimensions,
                available=p.provider in connected,
            )
            for p in PROVIDERS
            for e in p.embedding_models
        ],
    )


@router.get("/llm-settings", response_model=LlmSettingsOut)
async def get_llm_settings(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> LlmSettingsOut:
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return await _settings_payload(db, tenant)


@router.put("/llm-settings", response_model=LlmSettingsOut)
async def update_llm_settings(
    body: LlmSettingsIn,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> LlmSettingsOut:
    """Choose the model this workspace drafts with.

    Rejects a model whose provider the tenant has no key for — otherwise the
    failure would surface much later, as a broken campaign.
    """
    if user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
        )
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    # Treat omitted fields as "leave alone" and an explicit null as "reset".
    # Assigning both unconditionally meant a client sending only the chat model
    # silently cleared the embedding model — which changes how future chunks
    # are embedded and leaves existing vectors unsearchable.
    provided = body.model_fields_set
    for field_name in ("default_llm_model", "embedding_llm_model"):
        if field_name not in provided:
            continue
        model = getattr(body, field_name)
        if model is None:
            continue
        try:
            provider = provider_for_model(model)
        except UnknownProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        creds = await load_credentials(db, tenant_id=user.tenant_id, provider=provider)
        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=f"Connect a {provider} API key before selecting {model}.",
            )

    if "embedding_llm_model" in provided and body.embedding_llm_model is not None:
        # The knowledge-base vector column is a fixed width, so an embedding
        # model of any other size would fail at insert time, long after the
        # user made the choice.
        spec = embedding_spec(body.embedding_llm_model)
        if spec is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{body.embedding_llm_model} is not a supported embedding model. "
                    f"The knowledge base requires {EMBEDDING_DIM}-dimension embeddings."
                ),
            )

    if "default_llm_model" in provided:
        tenant.default_llm_model = body.default_llm_model
    if "embedding_llm_model" in provided:
        tenant.embedding_llm_model = body.embedding_llm_model
    await db.flush()
    await write_audit_event(
        db,
        action="tenant.llm_model_changed",
        target_type="tenant",
        target_id=user.tenant_id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={
            "default_llm_model": body.default_llm_model,
            "embedding_llm_model": body.embedding_llm_model,
        },
    )
    return await _settings_payload(db, tenant)


__all__ = ["router"]
