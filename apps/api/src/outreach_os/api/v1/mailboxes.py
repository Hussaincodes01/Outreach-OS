"""Mailbox endpoints — connect Gmail/Outlook/SMTP and send a test email."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_db, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.errors import MailError, OAuthError
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.schemas.mailbox import (
    MailboxOut,
    OAuthStartResponse,
    SendTestRequest,
    SmtpCreate,
)
from outreach_os.services import vault_service
from outreach_os.services.mailbox import gmail_oauth, graph_oauth, mailer

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


# ----------------- helpers -----------------


def _to_out(m: Mailbox) -> MailboxOut:
    return MailboxOut(
        id=m.id,
        provider=m.provider,
        email_address=m.email_address,
        is_active=m.is_active,
        daily_send_cap=m.daily_send_cap,
        created_at=m.created_at,
    )


def _require_admin(user: AuthContext) -> None:
    if user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
        )


# ----------------- list / delete -----------------


@router.get("", response_model=list[MailboxOut])
async def list_mailboxes(
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> list[MailboxOut]:
    result = await db.execute(select(Mailbox).order_by(Mailbox.created_at.desc()))
    return [_to_out(m) for m in result.scalars().all()]


@router.delete("/{mailbox_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mailbox(
    mailbox_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    _require_admin(user)
    m = await db.get(Mailbox, mailbox_id)
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="mailbox not found"
        )
    await db.delete(m)
    await write_audit_event(
        db,
        action="mailbox.disconnected",
        target_type="mailbox",
        target_id=mailbox_id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"provider": m.provider, "email_address": m.email_address},
    )


# ----------------- Gmail OAuth -----------------


@router.get("/oauth/gmail/start", response_model=OAuthStartResponse)
async def gmail_start(
    user: AuthContext = Depends(get_current_user),
) -> OAuthStartResponse:
    _require_admin(user)
    state = gmail_oauth.build_state_token(
        user_id=user.user_id, tenant_id=user.tenant_id
    )
    try:
        url = gmail_oauth.build_auth_url(state)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return OAuthStartResponse(auth_url=url, state=state)


@router.get("/oauth/gmail/callback")
async def gmail_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Google redirects the user-agent here. The state token carries the
    user/tenant identity. The request has NO bearer token (browser
    redirect), so we use the unscoped session, resolve the tenant from
    the state, then bind RLS for the mailbox write.

    Phase 0+1 keeps this a stub that returns 501; the real flow (decode
    id_token, exchange code, persist refresh_token) is Phase 4 work.
    """
    claims = gmail_oauth.verify_state_token(state)
    tenant_id = uuid.UUID(str(claims["tenant_id"]))
    await db.execute(
        text("SELECT set_config('app.current_tenant', :t, true)"),
        {"t": str(tenant_id)},
    )
    # We do not actually exchange the code or write the mailbox in Phase 0+1.
    # The full implementation lands in Phase 4; in the meantime the auth
    # URL builder is what we want to verify works.
    return {
        "status": "phase4_pending",
        "tenant_id": str(tenant_id),
        "code_prefix": code[:6] + "…",
    }


# ----------------- Outlook OAuth -----------------


@router.get("/oauth/outlook/start", response_model=OAuthStartResponse)
async def outlook_start(
    user: AuthContext = Depends(get_current_user),
) -> OAuthStartResponse:
    _require_admin(user)
    state = graph_oauth.build_state_token(
        user_id=user.user_id, tenant_id=user.tenant_id, email_hint=""
    )
    try:
        url = graph_oauth.build_auth_url(state)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return OAuthStartResponse(auth_url=url, state=state)


@router.get("/oauth/outlook/callback")
async def outlook_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    claims = graph_oauth.verify_state_token(state)
    tenant_id = uuid.UUID(str(claims["tenant_id"]))
    await db.execute(
        text("SELECT set_config('app.current_tenant', :t, true)"),
        {"t": str(tenant_id)},
    )
    return {
        "status": "phase4_pending",
        "tenant_id": str(tenant_id),
        "code_prefix": code[:6] + "…",
    }


# ----------------- SMTP -----------------


@router.post("/smtp", response_model=MailboxOut, status_code=status.HTTP_201_CREATED)
async def create_smtp_mailbox(
    payload: SmtpCreate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> MailboxOut:
    _require_admin(user)
    cfg = {
        "host": payload.host,
        "port": payload.port,
        "username": payload.username,
        "password": payload.password,
        "use_tls": payload.use_tls,
    }
    ciphertext = vault_service.encrypt_for_tenant(str(user.tenant_id), cfg)
    m = Mailbox(
        tenant_id=user.tenant_id,
        provider="smtp",
        email_address=payload.email_address.lower(),
        smtp_config_ciphertext=ciphertext,
        daily_send_cap=payload.daily_send_cap,
    )
    db.add(m)
    try:
        await db.flush()
    except Exception as exc:  # unique violation
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"mailbox already exists: {exc}",
        ) from exc
    await write_audit_event(
        db,
        action="mailbox.connected",
        target_type="mailbox",
        target_id=m.id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={"provider": "smtp", "email_address": m.email_address},
    )
    return _to_out(m)


# ----------------- send test -----------------


@router.post("/{mailbox_id}/send-test")
async def send_test(
    mailbox_id: uuid.UUID,
    payload: SendTestRequest,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> dict[str, str]:
    m = await db.get(Mailbox, mailbox_id)
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="mailbox not found"
        )
    try:
        result = await mailer.send_test_email(
            db,
            mailbox=m,
            to=payload.to,
            subject=payload.subject,
            body=payload.body,
            actor_id=user.user_id,
        )
    except MailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return result
