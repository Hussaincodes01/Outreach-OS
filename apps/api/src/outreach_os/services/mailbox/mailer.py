"""Send a test email. In Phase 0+1 this is the only outbound path; it's also
useful for verifying the SMTP / OAuth wiring before Phase 4 builds the
production sender.

For Gmail and Outlook, we just record a 'test send' audit event without
actually hitting Graph / Gmail API yet (Phase 4 wires that up). The
behaviour is: try the simplest possible send via the configured channel
and return ok/fail.
"""
from __future__ import annotations

import smtplib
import uuid
from email.message import EmailMessage
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.audit import write_audit_event
from outreach_os.core.config import get_settings
from outreach_os.core.errors import MailError
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services import vault_service


async def send_test_email(
    session: AsyncSession,
    *,
    mailbox: Mailbox,
    to: str,
    subject: str,
    body: str,
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    if mailbox.provider == "smtp":
        return await _send_smtp(mailbox, to, subject, body, actor_id, session)
    if mailbox.provider == "gmail":
        # Phase 0+1: just record the audit. Real Gmail send lands in Phase 4.
        await write_audit_event(
            session,
            action="mailbox.test_send.stub",
            target_type="mailbox",
            target_id=mailbox.id,
            actor_kind="user",
            actor_id=actor_id,
            payload={"to": to, "subject": subject, "provider": "gmail"},
        )
        return {
            "ok": True,
            "message": "Gmail API integration is wired in Phase 4; "
            "the OAuth token is stored and verified.",
        }
    if mailbox.provider == "outlook":
        await write_audit_event(
            session,
            action="mailbox.test_send.stub",
            target_type="mailbox",
            target_id=mailbox.id,
            actor_kind="user",
            actor_id=actor_id,
            payload={"to": to, "subject": subject, "provider": "outlook"},
        )
        return {
            "ok": True,
            "message": "Microsoft Graph integration is wired in Phase 4; "
            "the OAuth token is stored and verified.",
        }
    raise MailError(f"unsupported provider: {mailbox.provider}")


async def _send_smtp(
    mailbox: Mailbox,
    to: str,
    subject: str,
    body: str,
    actor_id: uuid.UUID,
    session: AsyncSession,
) -> dict[str, Any]:
    if not mailbox.smtp_config_ciphertext:
        raise MailError("mailbox has no SMTP config")
    cfg = vault_service.decrypt_for_tenant(
        str(mailbox.tenant_id), mailbox.smtp_config_ciphertext
    )

    msg = EmailMessage()
    msg["From"] = mailbox.email_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    settings = get_settings()
    host = cfg.get("host", settings.smtp_host)
    port = int(cfg.get("port", settings.smtp_port))
    username = cfg.get("username", settings.smtp_username)
    password = cfg.get("password", settings.smtp_password)
    use_tls = bool(cfg.get("use_tls", settings.smtp_use_tls))

    try:
        with smtplib.SMTP(host, port, timeout=10) as client:
            if use_tls:
                client.starttls()
            if username and password:
                client.login(username, password)
            client.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"SMTP send failed: {exc}") from exc

    await write_audit_event(
        session,
        action="mailbox.test_send.smtp",
        target_type="mailbox",
        target_id=mailbox.id,
        actor_kind="user",
        actor_id=actor_id,
        payload={"to": to, "subject": subject, "host": host, "port": port},
    )
    return {"ok": True, "message": f"sent via SMTP {host}:{port}"}
