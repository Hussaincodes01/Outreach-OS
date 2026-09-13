"""Outbound transport for a connected mailbox.

Campaign mail must leave through the user's own mailbox — never a shared
platform server — so recipients see a real sender and replies land in an inbox
the user controls.
"""
from __future__ import annotations

from typing import Any

from outreach_os.core.errors import MailError
from outreach_os.core.mailer import MailerClient, SmtpMailer
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services import vault_service


def smtp_config(mailbox: Mailbox) -> dict[str, Any]:
    """Decrypt and return the mailbox's stored SMTP settings.

    Task 6 adds IMAP keys (host/port/ssl) to this same encrypted dict —
    keep the existing keys (`host`, `port`, `username`, `password`,
    `use_tls`) stable.
    """
    if mailbox.provider != "smtp" or not mailbox.smtp_config_ciphertext:
        raise MailError(f"mailbox {mailbox.email_address} has no SMTP configuration")
    try:
        cfg = vault_service.decrypt_for_tenant(str(mailbox.tenant_id), mailbox.smtp_config_ciphertext)
    except Exception as exc:
        raise MailError(f"mailbox {mailbox.email_address}: SMTP settings cannot be decrypted") from exc
    return dict(cfg)


def mailer_for_mailbox(mailbox: Mailbox) -> MailerClient:
    """Build a mailer that sends through this mailbox's own SMTP credentials."""
    cfg = smtp_config(mailbox)
    return SmtpMailer(
        host=str(cfg["host"]),
        port=int(cfg["port"]),
        username=str(cfg.get("username") or "") or None,
        password=str(cfg.get("password") or "") or None,
        use_tls=bool(cfg.get("use_tls", True)),
        default_from=mailbox.email_address,
    )


__all__ = ["mailer_for_mailbox", "smtp_config"]
