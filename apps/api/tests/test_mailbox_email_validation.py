"""POST /v1/mailboxes/smtp accepts local/dev test-server addresses.

Regression test for a bug the e2e smoke script (scripts/e2e_smoke.py) found:
`SmtpCreate.email_address` and `SendTestRequest.to` used pydantic's
`EmailStr`, which rejects any address on an RFC 2606 special-use domain
(`.test`, `.example`, `.invalid`, `.localhost`) as "a special-use or
reserved name that cannot be used with email". That made it impossible to
connect a mailbox to GreenMail (`*@greenmail.test`), the local SMTP/IMAP
server this project's own smoke test and manual e2e testing use -- a
single-user, self-hosted tool should be able to point a mailbox at any
locally reachable mail server. `domain/schemas/mailbox.py` now validates
with a permissive regex (mirroring `services/lead_import.py`'s email check)
instead, and clearly malformed input is still rejected.
"""
from __future__ import annotations


async def test_smtp_mailbox_accepts_dot_test_domain(client) -> None:
    r = await client.post(
        "/v1/mailboxes/smtp",
        json={
            "host": "greenmail",
            "port": 3025,
            "username": "sender@greenmail.test",
            "password": "sender@greenmail.test",
            "email_address": "sender@greenmail.test",
            "use_tls": False,
            "imap_host": "greenmail",
            "imap_port": 3143,
            "imap_use_ssl": False,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email_address"] == "sender@greenmail.test"
    assert body["imap_enabled"] is True


async def test_smtp_mailbox_rejects_malformed_email(client) -> None:
    r = await client.post(
        "/v1/mailboxes/smtp",
        json={
            "host": "smtp.example.org",
            "port": 587,
            "username": "me",
            "password": "pw",
            "email_address": "not-an-email",
        },
    )
    assert r.status_code == 422, r.text


async def test_send_test_accepts_dot_test_recipient(client) -> None:
    r = await client.post(
        "/v1/mailboxes/smtp",
        json={
            "host": "greenmail",
            "port": 3025,
            "username": "sender2@greenmail.test",
            "password": "sender2@greenmail.test",
            "email_address": "sender2@greenmail.test",
            "use_tls": False,
        },
    )
    assert r.status_code == 201, r.text
    mailbox_id = r.json()["id"]

    # send-test itself will fail to actually deliver (no real SMTP server at
    # "greenmail" from the test process), but validation must accept the
    # `.test` recipient and get past the schema layer to the mailer call.
    r = await client.post(
        f"/v1/mailboxes/{mailbox_id}/send-test",
        json={"to": "prospect@greenmail.test"},
    )
    assert r.status_code != 422, r.text
