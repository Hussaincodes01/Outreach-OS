"""Transactional email for account actions: reset links and verification.

Sent from the platform's own SMTP, never through a tenant's campaign mailbox —
a password reset arriving from a prospect-facing address is confusing and hurts
deliverability of the real outbound.

Delivery is best-effort at the call site: the endpoints deliberately do not
fail when mail is down, because whether an address exists must not be
observable from the response.
"""
from __future__ import annotations

import logging
from email.utils import make_msgid

from outreach_os.core.config import get_settings
from outreach_os.core.mailer import OutgoingMessage, get_transactional_mailer

log = logging.getLogger(__name__)


def _link(path: str, token: str) -> str:
    settings = get_settings()
    base = settings.web_base_url.rstrip("/")
    return f"{base}{path}?token={token}"


def _send(*, to_email: str, subject: str, body_text: str) -> bool:
    settings = get_settings()
    message = OutgoingMessage(
        to_email=to_email,
        from_email=settings.transactional_from_email,
        subject=subject,
        body_text=body_text,
        message_id_header=make_msgid(),
        # Transactional mail must never be bundled into a marketing thread or
        # auto-replied to by an out-of-office.
        headers={"Auto-Submitted": "auto-generated", "X-Auto-Response-Suppress": "All"},
    )
    try:
        get_transactional_mailer().send(message)
        return True
    except Exception:
        # Never raise: the caller's response must not reveal whether the
        # address exists, and a mail outage should not break signup.
        log.exception("transactional email failed subject=%r", subject)
        return False


def send_password_reset(*, to_email: str, token: str) -> bool:
    link = _link("/reset-password", token)
    minutes = get_settings().password_reset_ttl_minutes
    return _send(
        to_email=to_email,
        subject="Reset your Outreach OS password",
        body_text=(
            "Someone asked to reset the password for this Outreach OS account.\n\n"
            f"Set a new password:\n{link}\n\n"
            f"The link expires in {minutes} minutes and can be used once.\n\n"
            "If this wasn't you, no action is needed — your password has not "
            "changed and the link above will expire on its own.\n"
        ),
    )


def send_email_verification(*, to_email: str, token: str) -> bool:
    link = _link("/verify-email", token)
    hours = get_settings().email_verification_ttl_hours
    return _send(
        to_email=to_email,
        subject="Confirm your email address",
        body_text=(
            "Welcome to Outreach OS.\n\n"
            f"Confirm this address:\n{link}\n\n"
            f"The link expires in {hours} hours.\n\n"
            "If you didn't create an account, you can ignore this email.\n"
        ),
    )


__all__ = ["send_email_verification", "send_password_reset"]
