"""Mailbox endpoints — connect an SMTP mailbox and send a test email.

Gmail/Outlook OAuth mailbox connection is removed: SMTP (which works with
Gmail/Outlook app passwords) is the only supported transport.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.core.errors import MailError
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.schemas.mailbox import MailboxOut, SendTestRequest, SmtpCreate
from outreach_os.services import vault_service
from outreach_os.services.mailbox import mailer
from outreach_os.services.mailbox.transport import smtp_config

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


# ----------------- helpers -----------------


def _imap_enabled(m: Mailbox) -> bool:
    """Whether this mailbox has IMAP settings stored (the inbox poller will
    pick it up). Decrypting just to check this is cheap; a decrypt failure
    (corrupt/missing config, non-SMTP provider) reads as False rather than
    raising out of a list endpoint."""
    try:
        cfg = smtp_config(m)
    except MailError:
        return False
    return bool(cfg.get("imap_host"))


def _to_out(m: Mailbox) -> MailboxOut:
    return MailboxOut(
        id=m.id,
        provider=m.provider,
        email_address=m.email_address,
        is_active=m.is_active,
        daily_send_cap=m.daily_send_cap,
        created_at=m.created_at,
        imap_enabled=_imap_enabled(m),
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


# ----------------- SMTP -----------------


@router.post("/smtp", response_model=MailboxOut, status_code=status.HTTP_201_CREATED)
async def create_smtp_mailbox(
    payload: SmtpCreate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> MailboxOut:
    _require_admin(user)
    cfg: dict[str, object] = {
        "host": payload.host,
        "port": payload.port,
        "username": payload.username,
        "password": payload.password,
        "use_tls": payload.use_tls,
    }
    # Only store the IMAP keys when the caller actually wants IMAP polling --
    # a bare `smtp_config()` dict without them keeps older send-only
    # mailboxes and `_imap_enabled()` both working unchanged.
    if payload.imap_host:
        cfg["imap_host"] = payload.imap_host
        cfg["imap_port"] = payload.imap_port
        cfg["imap_use_ssl"] = payload.imap_use_ssl
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
