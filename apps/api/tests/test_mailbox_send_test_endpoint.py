"""POST /v1/mailboxes/{id}/send-test returns a response FastAPI can serialize.

Regression test for a bug the e2e smoke script (scripts/e2e_smoke.py)
found against the live stack: `send_test`'s return type annotation was
`-> dict[str, str]`, which FastAPI uses as an implicit response_model.
`services/mailbox/mailer.send_test_email` actually returns
`{"ok": True, "message": "..."}` -- a bool for "ok", not a str -- so every
real send-test call failed response serialization with a 500
`ResponseValidationError`, even though the send itself succeeded. Only the
subject/body request-validation paths (422s) had ever been exercised
before; this is the first test to reach a successful response. The route
now returns `domain.schemas.mailbox.SendTestResult` (ok: bool, message:
str) explicitly instead of relying on the loosely-typed dict.
"""
from __future__ import annotations

import pytest


async def _create_mailbox(client) -> str:
    r = await client.post(
        "/v1/mailboxes/smtp",
        json={
            "host": "smtp.example.org",
            "port": 587,
            "username": "me@example.org",
            "password": "app-password",
            "email_address": "me@example.org",
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_send_test_response_serializes(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact shape the real mailer returns on success must survive
    FastAPI's response validation instead of 500ing."""
    mailbox_id = await _create_mailbox(client)

    async def _fake_send_test_email(*args, **kwargs):
        return {"ok": True, "message": "sent via SMTP smtp.example.org:587"}

    monkeypatch.setattr(
        "outreach_os.services.mailbox.mailer.send_test_email",
        _fake_send_test_email,
    )

    r = await client.post(
        f"/v1/mailboxes/{mailbox_id}/send-test",
        json={"to": "prospect@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ok": True, "message": "sent via SMTP smtp.example.org:587"}


async def test_send_test_mail_error_still_maps_to_502(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The existing MailError -> 502 mapping must be unaffected by the
    response-model change."""
    from outreach_os.core.errors import MailError

    mailbox_id = await _create_mailbox(client)

    async def _fake_send_test_email(*args, **kwargs):
        raise MailError("SMTP send failed: connection refused")

    monkeypatch.setattr(
        "outreach_os.services.mailbox.mailer.send_test_email",
        _fake_send_test_email,
    )

    r = await client.post(
        f"/v1/mailboxes/{mailbox_id}/send-test",
        json={"to": "prospect@example.com"},
    )
    assert r.status_code == 502, r.text
