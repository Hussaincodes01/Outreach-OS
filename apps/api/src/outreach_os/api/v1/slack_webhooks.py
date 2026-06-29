"""Slack incoming-webhook configuration.

The URL is encrypted via the Phase 1 vault and stored in a `Credential`
row; this router only manages the pointer (SlackWebhook). One row per
tenant per name (default: "default").
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.models.slack_webhook import SlackWebhook
from outreach_os.domain.schemas.phase6 import SlackWebhookIn, SlackWebhookOut
from outreach_os.services.credential_lookup import create_credential

router = APIRouter(prefix="/slack-webhooks", tags=["notifications"])


def _to_out(h: SlackWebhook) -> SlackWebhookOut:
    return SlackWebhookOut(
        id=h.id,
        name=h.name,
        channel=h.channel,
        status=h.status,
        last_error=h.last_error,
        last_delivered_at=h.last_delivered_at,
        created_at=h.created_at,
        updated_at=h.updated_at,
    )


@router.get("", response_model=list[SlackWebhookOut])
async def list_webhooks(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[SlackWebhookOut]:
    rows = (
        (
            await db.execute(
                select(SlackWebhook).order_by(SlackWebhook.name)
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post("", response_model=SlackWebhookOut, status_code=201)
async def create_webhook(
    body: SlackWebhookIn,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SlackWebhookOut:
    cred = await create_credential(
        db,
        tenant_id=_user.tenant_id,
        kind="slack_webhook",
        plaintext={"webhook_url": body.webhook_url},
        label=f"slack_webhook:{body.name}",
    )
    hook = SlackWebhook(
        tenant_id=_user.tenant_id,
        name=body.name,
        webhook_url_credential_id=cred.id,
        channel=body.channel,
        status="active",
    )
    db.add(hook)
    await db.flush()
    return _to_out(hook)


@router.delete("/{hook_id}", status_code=204)
async def delete_webhook(
    hook_id: uuid.UUID,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    hook = (
        await db.execute(
            select(SlackWebhook).where(SlackWebhook.id == hook_id)
        )
    ).scalar_one_or_none()
    if hook is None:
        raise HTTPException(status_code=404, detail="webhook not found")
    await db.delete(hook)


@router.post("/{hook_id}/pause", response_model=SlackWebhookOut)
async def pause_webhook(
    hook_id: uuid.UUID,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SlackWebhookOut:
    hook = (
        await db.execute(
            select(SlackWebhook).where(SlackWebhook.id == hook_id)
        )
    ).scalar_one_or_none()
    if hook is None:
        raise HTTPException(status_code=404, detail="webhook not found")
    hook.status = "paused"
    hook.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _to_out(hook)


@router.post("/{hook_id}/resume", response_model=SlackWebhookOut)
async def resume_webhook(
    hook_id: uuid.UUID,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> SlackWebhookOut:
    hook = (
        await db.execute(
            select(SlackWebhook).where(SlackWebhook.id == hook_id)
        )
    ).scalar_one_or_none()
    if hook is None:
        raise HTTPException(status_code=404, detail="webhook not found")
    hook.status = "active"
    hook.last_error = None
    hook.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _to_out(hook)


__all__ = ["router"]
