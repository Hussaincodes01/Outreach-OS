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


@pytest.mark.parametrize("use_ssl", [True, False])
def test_imap_connection_uses_configured_timeout(monkeypatch, use_ssl: bool) -> None:
    """I2: every IMAP connection gets a socket timeout, so a stalled server
    cannot hang the poll (and the worker slot) forever."""
    import imaplib

    from outreach_os.core.config import get_settings
    from outreach_os.services.mailbox import inbox as inbox_module

    recorded: list[dict] = []

    class _FakeImap:
        def __init__(self, host: str, port: int, **kwargs) -> None:
            recorded.append({"cls": type(self).__name__, "host": host, "port": port, **kwargs})

        def login(self, username: str, password: str) -> None:
            pass

        def select(self, mailbox: str) -> None:
            pass

    class FakeIMAP4(_FakeImap):
        pass

    class FakeIMAP4_SSL(_FakeImap):  # noqa: N801 - mirrors imaplib's name
        pass

    monkeypatch.setattr(imaplib, "IMAP4", FakeIMAP4)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP4_SSL)

    inbox_module._connect(
        {
            "imap_host": "imap.example.org",
            "imap_port": 993 if use_ssl else 143,
            "imap_use_ssl": use_ssl,
            "username": "me@example.org",
            "password": "app-password",
        }
    )
    assert len(recorded) == 1
    assert recorded[0]["cls"] == ("FakeIMAP4_SSL" if use_ssl else "FakeIMAP4")
    assert recorded[0]["timeout"] == get_settings().imap_timeout_seconds
    assert get_settings().imap_timeout_seconds == 30


def test_celery_has_task_time_limits_and_beat_entries_expire() -> None:
    """I2: tasks have default soft/hard time limits, and the frequent beat
    entries expire so a backlog of stale queued runs is dropped rather than
    executed late in a burst."""
    from outreach_os.core.config import get_settings

    settings = get_settings()
    assert settings.celery_task_soft_time_limit_seconds == 300
    assert settings.celery_task_time_limit_seconds == 360
    assert celery_app.conf.task_soft_time_limit == settings.celery_task_soft_time_limit_seconds
    assert celery_app.conf.task_time_limit == settings.celery_task_time_limit_seconds
    schedule = celery_app.conf.beat_schedule
    for name in ("outreach_os.workers.send_due", "outreach_os.workers.poll_inboxes"):
        expires = schedule[name].get("options", {}).get("expires")
        assert expires is not None, name
        assert 0 < expires <= float(schedule[name]["schedule"]), name


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
    marked: list[bytes] = []
    summary = await poll_inboxes_async(
        fetch=lambda cfg: [(b"1", _raw_reply(message_id))],
        mark_seen=lambda cfg, uids: marked.extend(uids),
    )
    assert summary["ingested"] == 1
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["from_email"] == "pat@prospect.example" for r in items)
    # The ingested (and durably committed) message's uid was marked seen.
    assert marked == [b"1"]


async def test_poll_rebinds_tenant_after_duplicate_so_later_messages_ingest(client, sent_send) -> None:
    """First message is a duplicate (already ingested); ReplyService.ingest
    rolls the session back on the IntegrityError, which also clears the
    transaction-scoped RLS GUC. The second, brand-new message must still
    ingest -- proving poll_mailbox re-binds the tenant after a None result."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    dup_raw = _raw_reply(message_id, message_id="<dup-reply@prospect.example>")
    new_raw = _raw_reply(message_id, message_id="<fresh-reply@prospect.example>")

    # A no-op mark_seen: the default real one would try to actually connect
    # to the fixture's fake "imap.example.org" host.
    def _noop_mark_seen(cfg: dict, uids: list[bytes]) -> None:
        pass

    # Ingest the "duplicate" once up front so the second poll sees it as one.
    summary1 = await poll_inboxes_async(
        fetch=lambda cfg: [(b"1", dup_raw)], mark_seen=_noop_mark_seen
    )
    assert summary1["ingested"] == 1

    summary2 = await poll_inboxes_async(
        fetch=lambda cfg: [(b"1", dup_raw), (b"2", new_raw)], mark_seen=_noop_mark_seen
    )
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

    summary = await poll_inboxes_async(
        fetch=lambda cfg: [(b"1", first_raw), (b"2", dup_raw)],
        mark_seen=lambda cfg, uids: None,
    )
    assert summary["ingested"] == 1
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["message_id_header"] == "<first-reply@prospect.example>" for r in items)


async def test_poll_isolates_a_failing_message_and_only_marks_the_others_seen(
    client, sent_send, monkeypatch
) -> None:
    """One message's classification blowing up (any non-IntegrityError
    exception from deep inside ReplyService.ingest) must not abort the rest
    of the mailbox's batch, and that message's uid must not be handed to
    mark_seen -- it was never durably ingested, so it must come back on the
    next poll instead of being silently lost."""
    from outreach_os.services.reply_service import ReplyService
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    bad_raw = _raw_reply(message_id, message_id="<bad-reply@prospect.example>")
    good_raw = _raw_reply(message_id, message_id="<good-reply@prospect.example>")

    original = ReplyService._classify_and_act

    async def _boom(self, *, tenant_id, reply, send):
        if reply.message_id_header == "<bad-reply@prospect.example>":
            raise RuntimeError("classification exploded")
        return await original(self, tenant_id=tenant_id, reply=reply, send=send)

    monkeypatch.setattr(ReplyService, "_classify_and_act", _boom)

    marked: list[bytes] = []
    summary = await poll_inboxes_async(
        fetch=lambda cfg: [(b"1", bad_raw), (b"2", good_raw)],
        mark_seen=lambda cfg, uids: marked.extend(uids),
    )
    assert summary["ingested"] == 1  # only the good one
    assert summary["errors"] == 0  # the mailbox-level guard never saw it
    assert marked == [b"2"]  # the bad message's uid was withheld
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["message_id_header"] == "<good-reply@prospect.example>" for r in items)
    assert not any(r["message_id_header"] == "<bad-reply@prospect.example>" for r in items)


async def test_poll_skips_unparseable_message_without_marking_it_seen(
    client, sent_send, monkeypatch
) -> None:
    """A malformed message that makes parse_message raise is skipped (not
    marked seen, so it is retried next poll) while the rest of the batch
    still proceeds."""
    from outreach_os.services.mailbox import inbox as inbox_module
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    bad_raw = b"BADMARKER not a real email at all"
    good_raw = _raw_reply(message_id, message_id="<ok-reply@prospect.example>")

    original_parse = inbox_module.parse_message

    def _flaky_parse(raw: bytes):
        if b"BADMARKER" in raw:
            raise ValueError("not parseable")
        return original_parse(raw)

    monkeypatch.setattr(inbox_module, "parse_message", _flaky_parse)

    marked: list[bytes] = []
    summary = await poll_inboxes_async(
        fetch=lambda cfg: [(b"1", bad_raw), (b"2", good_raw)],
        mark_seen=lambda cfg, uids: marked.extend(uids),
    )
    assert summary["ingested"] == 1
    assert marked == [b"2"]
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["message_id_header"] == "<ok-reply@prospect.example>" for r in items)


async def test_poll_mark_seen_failure_does_not_lose_already_ingested_replies(client, sent_send) -> None:
    """If mark_seen blows up (e.g. the IMAP connection drops between
    fetching and flagging), replies already ingested and committed earlier
    in that same poll must still be there -- the failure is isolated to
    the (idempotent, safe-to-retry) seen-flagging step."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    raw = _raw_reply(message_id, message_id="<durable-reply@prospect.example>")

    def _boom_mark_seen(cfg: dict, uids: list[bytes]) -> None:
        raise OSError("connection reset")

    summary = await poll_inboxes_async(
        fetch=lambda cfg: [(b"1", raw)],
        mark_seen=_boom_mark_seen,
    )
    # poll_mailbox raised (mark_seen's OSError propagates through to the
    # worker's per-mailbox guard), but the reply it already committed
    # before that point is not undone.
    assert summary["errors"] == 1
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(r["message_id_header"] == "<durable-reply@prospect.example>" for r in items)


async def _add_second_imap_mailbox(client) -> str:
    r = await client.post(
        "/v1/mailboxes/smtp",
        json={
            "host": "smtp.example.org",
            "port": 587,
            "username": "second@example.org",
            "password": "app-password-2",
            "email_address": "second@example.org",
            "imap_host": "imap2.example.org",
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_poll_failing_mailbox_does_not_abort_later_mailboxes(client, sent_send) -> None:
    """C1 regression: the FIRST mailbox polled fails at the mailbox level
    (fetch raises OSError). The rollback that follows must not expire the
    second mailbox's ORM state -- the second mailbox is still polled and its
    reply ingested, and the run reports one error instead of crashing with
    MissingGreenlet."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    await _add_second_imap_mailbox(client)
    raw = _raw_reply(message_id, message_id="<second-mailbox-reply@prospect.example>")
    calls: list[str] = []

    def _fetch(cfg: dict) -> list[tuple[bytes, bytes]]:
        calls.append(str(cfg["username"]))
        if len(calls) == 1:
            raise OSError("imap host unreachable")
        return [(b"1", raw)]

    summary = await poll_inboxes_async(fetch=_fetch, mark_seen=lambda cfg, uids: None)
    assert summary == {"mailboxes": 2, "ingested": 1, "errors": 1}
    assert len(calls) == 2
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    assert any(
        r["message_id_header"] == "<second-mailbox-reply@prospect.example>" for r in items
    )


async def test_poll_duplicate_in_first_mailbox_does_not_abort_later_mailboxes(
    client, sent_send
) -> None:
    """C1 regression: the first mailbox's batch contains a duplicate
    Message-ID, which forces ReplyService.ingest's per-message rollback. That
    rollback must not break the next mailbox -- its reply still ingests and
    no exception escapes."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    _mailbox_id, message_id = sent_send
    await _add_second_imap_mailbox(client)
    first_raw = _raw_reply(message_id, message_id="<mb1-reply@prospect.example>")
    dup_raw = _raw_reply(message_id, message_id="<mb1-reply@prospect.example>")
    other_raw = _raw_reply(message_id, message_id="<mb2-reply@prospect.example>")
    calls: list[str] = []

    def _fetch(cfg: dict) -> list[tuple[bytes, bytes]]:
        calls.append(str(cfg["username"]))
        if len(calls) == 1:
            return [(b"1", first_raw), (b"2", dup_raw)]
        return [(b"7", other_raw)]

    summary = await poll_inboxes_async(fetch=_fetch, mark_seen=lambda cfg, uids: None)
    assert summary == {"mailboxes": 2, "ingested": 2, "errors": 0}
    replies = (await client.get("/v1/replies")).json()
    items = replies["items"] if isinstance(replies, dict) else replies
    ids = {r["message_id_header"] for r in items}
    assert "<mb1-reply@prospect.example>" in ids
    assert "<mb2-reply@prospect.example>" in ids


def test_fetch_unseen_against_real_greenmail_imap() -> None:
    """Exercise the real IMAP client against the dev-stack GreenMail server
    (no auth; any mailbox is auto-created on first delivery). Skipped, not
    failed, when localhost:3143 is unreachable. Proves fetch_unseen's PEEK
    never marks a message seen on its own, and mark_seen is what actually
    does so."""
    import smtplib
    import socket
    import uuid

    from outreach_os.services.mailbox.inbox import fetch_unseen, mark_seen

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

    cfg = {
        "imap_host": "localhost",
        "imap_port": 3143,
        "imap_use_ssl": False,
        "username": address,
        "password": address,
    }

    raws = fetch_unseen(cfg)
    assert len(raws) == 1
    uid, raw = raws[0]
    parsed = parse_message(raw)
    assert parsed is not None
    assert parsed.subject == "Real IMAP fetch"
    assert "GreenMail" in parsed.body_text

    # BODY.PEEK[] never marks the message \Seen -- fetching again still
    # returns it, unlike the old RFC822-fetch-marks-seen behaviour.
    raws_again = fetch_unseen(cfg)
    assert len(raws_again) == 1
    assert raws_again[0][0] == uid

    mark_seen(cfg, [uid])

    # Now that it's explicitly been marked seen, it drops out of UNSEEN.
    assert fetch_unseen(cfg) == []
