"""Send a test email through the mailbox's own SMTP transport.

Used both to verify SMTP credentials right after a mailbox is connected and
as the production sender for `POST /v1/mailboxes/{id}/send-test`. SMTP is the
only mailbox provider now — Gmail/Outlook OAuth mailboxes are removed; app
passwords cover both via SMTP.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.audit import write_audit_event
from outreach_os.core.errors import MailError
from outreach_os.core.mailer import MailerError, OutgoingMessage
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services.mailbox.transport import mailer_for_mailbox, smtp_config


async def send_test_email(
    session: AsyncSession,
    *,
    mailbox: Mailbox,
    to: str,
    subject: str,
    body: str,
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    if mailbox.provider != "smtp":
        raise MailError(f"unsupported provider: {mailbox.provider}")
    return await _send_smtp(mailbox, to, subject, body, actor_id, session)


async def _send_smtp(
    mailbox: Mailbox,
    to: str,
    subject: str,
    body: str,
    actor_id: uuid.UUID,
    session: AsyncSession,
) -> dict[str, Any]:
    cfg = smtp_config(mailbox)
    host, port = cfg.get("host"), cfg.get("port")
    mailer = mailer_for_mailbox(mailbox)
    try:
        mailer.send(
            OutgoingMessage(
                to_email=to,
                from_email=mailbox.email_address,
                subject=subject,
                body_text=body,
            )
        )
    except MailerError as exc:
        # `mailer_for_mailbox` raises the transport-agnostic `MailerError`;
        # translate to `MailError` so the route's existing `except MailError`
        # -> 502 mapping still applies.
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
