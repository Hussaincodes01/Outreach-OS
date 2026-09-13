"""IMAP replies are matched to the original send and ingested."""
from __future__ import annotations

from datetime import datetime, timedelta
from email.message import EmailMessage

import pytest

from outreach_os.services.mailbox.inbox import parse_message
from outreach_os.workers.celery_app import celery_app


def _raw_reply(in_reply_to: str, *, message_id: str = "<reply-1@prospect.example>") -> bytes:
    msg = EmailMessage()
    msg["From"] = "Pat Prospect <pat@prospect.example>"
    msg["To"] = "me@example.org"
    msg["Subject"] = "Re: Quick question"
    msg["Message-ID"] = message_id
    msg["In-Reply-To"] = in_reply_to
    msg["References"] = in_reply_to
    msg["Date"] = "Sun, 13 Sep 2026 10:00:00 +0000"
    msg.set_content("Sounds good, let's talk Tuesday.")
    msg.add_alternative("<p>Sounds good, let's talk Tuesday.</p>", subtype="html")
    return msg.as_bytes()


def test_parse_message_extracts_threading_headers() -> None:
    data = parse_message(_raw_reply("<send-abc@outreach>"))
    assert data is not None
    assert data.from_email == "pat@prospect.example"
    assert data.from_name == "Pat Prospect"
    assert data.message_id_header == "<reply-1@prospect.example>"
    assert data.in_reply_to == "<send-abc@outreach>"
    assert "Tuesday" in data.body_text
    assert data.body_html is not None
    assert "<p>" in data.body_html


def test_parse_message_without_message_id_is_skipped() -> None:
    msg = EmailMessage()
    msg["From"] = "x@y.example"
    msg.set_content("hi")
    assert parse_message(msg.as_bytes()) is None


def test_poll_inboxes_on_beat_schedule() -> None:
    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "outreach_os.workers.poll_inboxes" in tasks


# --- sent_send fixture -------------------------------------------------
#
# Builds: SMTP mailbox (with imap_host) -> lead -> campaign/sequence ->
# executed send, reusing the helpers test_phase4_send.py uses (campaign +
# lead seeded directly in DB, sequence started over HTTP, due step forced,
# SendService run directly) and the FakeLLMClient injection
# test_phase4_reply.py uses for reply classification.


@pytest.fixture
async def sent_send(client):
    from outreach_os.core.db import get_session_factory
    from outreach_os.core.llm import set_llm_client
    from outreach_os.core.tenancy import set_tenant_for_session
    from outreach_os.domain.models.lead import Lead
    from outreach_os.services.local_workspace import LOCAL_TENANT_ID, ensure_local_workspace
    from outreach_os.services.send_service import SendService
    from tests.fake_llm import FakeLLMClient
    from tests.test_phase4_send import select_sequence_step_for_run

    set_llm_client(FakeLLMClient())
    await ensure_local_workspace()

    # Mailbox, through the real endpoint, with imap_host set.
    r = await client.post(
        "/v1/mailboxes/smtp",
        json={
            "host": "smtp.example.org",
            "port": 587,
            "username": "me@example.org",
            "password": "app-password",
            "email_address": "me@example.org",
            "imap_host": "imap.example.org",
        },
    )
    assert r.status_code == 201, r.text
    mailbox_id = r.json()["id"]
    assert r.json()["imap_enabled"] is True

    # Campaign, through the real endpoint.
    r = await client.post(
        "/v1/campaigns",
        json={
            "name": "inbox-poll-camp",
            "style_sample_emails": ["Hi {first_name}, this is a test."],
            "steps": [{"step_number": 1, "delay_days": 0, "subject_template": "Quick question"}],
        },
    )
    assert r.status_code == 201, r.text
    campaign_id = r.json()["id"]

    # Lead, seeded directly (no lead-import endpoint used here).
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
        lead = Lead(
            tenant_id=LOCAL_TENANT_ID, source="serper",
            email="pat@prospect.example", first_name="Pat",
        )
        session.add(lead)
        await session.flush()
        lead_id = str(lead.id)

    # Sequence run, through the real endpoint.
    r = await client.post(
        "/v1/sequences",
        json={"campaign_id": campaign_id, "name": "inbox-poll-run", "lead_ids": [lead_id]},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    # Force the step due now, then run the send engine directly.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
        step = (await session.execute(
            select_sequence_step_for_run(run_id)
        )).scalar_one()
        step.scheduled_at = datetime.utcnow() - timedelta(seconds=5)

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
        svc = SendService(session)
        sends = await svc.execute_due(tenant_id=LOCAL_TENANT_ID)
    assert len(sends) == 1
    assert sends[0].status == "sent"
    message_id = sends[0].message_id_header

    yield mailbox_id, message_id
    set_llm_client(None)


async def test_poll_ingests_reply_for_real_send(client, sent_send) -> None:
    """`sent_send` fixture: an SMTP mailbox (with imap_host) plus a Send row in
    status 'sent' for the local workspace, created through the existing phase-4
    test helpers. Returns (mailbox_id, message_id_header)."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    summary = await poll_inboxes_async(fetch=lambda cfg: [_raw_reply(message_id)])
    assert summary["ingested"] == 1
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["from_email"] == "pat@prospect.example" for r in items)


async def test_poll_rebinds_tenant_after_duplicate_so_later_messages_ingest(client, sent_send) -> None:
    """First message is a duplicate (already ingested); ReplyService.ingest
    rolls the session back on the IntegrityError, which also clears the
    transaction-scoped RLS GUC. The second, brand-new message must still
    ingest -- proving poll_mailbox re-binds the tenant after a None result."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    dup_raw = _raw_reply(message_id, message_id="<dup-reply@prospect.example>")
    new_raw = _raw_reply(message_id, message_id="<fresh-reply@prospect.example>")

    # Ingest the "duplicate" once up front so the second poll sees it as one.
    summary1 = await poll_inboxes_async(fetch=lambda cfg: [dup_raw])
    assert summary1["ingested"] == 1

    summary2 = await poll_inboxes_async(fetch=lambda cfg: [dup_raw, new_raw])
    assert summary2["ingested"] == 1  # only the fresh one
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["message_id_header"] == "<fresh-reply@prospect.example>" for r in items)


async def test_poll_earlier_ingested_reply_survives_a_later_duplicate(client, sent_send) -> None:
    """Within a single poll pass, an earlier successfully-ingested reply must
    not be discarded when a *later* message in the same batch turns out to be
    a duplicate (ingest()'s rollback must not unwind prior, already-committed
    work in the same transaction)."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    first_raw = _raw_reply(message_id, message_id="<first-reply@prospect.example>")
    dup_raw = _raw_reply(message_id, message_id="<first-reply@prospect.example>")

    summary = await poll_inboxes_async(fetch=lambda cfg: [first_raw, dup_raw])
    assert summary["ingested"] == 1
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["message_id_header"] == "<first-reply@prospect.example>" for r in items)


def test_fetch_unseen_against_real_greenmail_imap() -> None:
    """Exercise the real IMAP client against the dev-stack GreenMail server
    (no auth; any mailbox is auto-created on first delivery). Skipped, not
    failed, when localhost:3143 is unreachable."""
    import smtplib
    import socket
    import uuid

    from outreach_os.services.mailbox.inbox import fetch_unseen

    try:
        with socket.create_connection(("localhost", 3143), timeout=2):
            pass
    except OSError:
        pytest.skip("GreenMail IMAP (localhost:3143) is not reachable")

    address = f"inbox-poll-{uuid.uuid4().hex[:8]}@greenmail.example"
    msg = EmailMessage()
    msg["From"] = "sender@greenmail.example"
    msg["To"] = address
    msg["Subject"] = "Real IMAP fetch"
    msg["Message-ID"] = f"<{uuid.uuid4().hex}@greenmail.example>"
    msg.set_content("Delivered straight through GreenMail's SMTP.")

    with smtplib.SMTP("localhost", 3025, timeout=5) as smtp:
        smtp.send_message(msg)

    raws = fetch_unseen(
        {
            "imap_host": "localhost",
            "imap_port": 3143,
            "imap_use_ssl": False,
            "username": address,
            "password": address,
        }
    )
    assert len(raws) == 1
    parsed = parse_message(raws[0])
    assert parsed is not None
    assert parsed.subject == "Real IMAP fetch"
    assert "GreenMail" in parsed.body_text
