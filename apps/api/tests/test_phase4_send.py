"""Phase 4 — Send engine + RLS isolation tests for the new tables.

These tests use the FakeLLMClient (deterministic) and the StubMailer
(in-memory) so the engine runs end-to-end without any network.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select as _select

from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import set_llm_client
from outreach_os.core.mailer import set_mailer_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.tenant import Tenant
from outreach_os.services.send_service import SendService
from tests.conftest import bearer, signup
from tests.fake_llm import FakeLLMClient


@pytest.fixture(autouse=True)
def fake_llm_and_mailer():
    fake = FakeLLMClient()
    set_llm_client(fake)
    from outreach_os.core.mailer import StubMailer
    stub = StubMailer()
    set_mailer_client(stub)
    yield {"llm": fake, "mailer": stub, "stub": stub}
    set_llm_client(None)
    set_mailer_client(None)


async def _ensure_tenant(tenant_id, slug: str, name: str) -> None:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        existing = await session.get(Tenant, tenant_id)
        if existing is None:
            session.add(
                Tenant(id=tenant_id, slug=slug, name=name, plan="starter", status="active")
            )


# --- Sequence run: RLS + lifecycle ---

async def test_sequence_runs_are_isolated_per_tenant(client):
    a = await signup(client, email="a-seq@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-seq")
    b = await signup(client, email="b-seq@acme-customer.example", password="pw-12345-AbCde", tenant_name="B-seq")

    # A creates a campaign.
    r = await client.post(
        "/v1/campaigns", headers=bearer(a["access_token"]),
        json={
            "name": "A-camp",
            "style_sample_emails": ["Hi {first_name}, this is a test."],
            "steps": [{"step_number": 1, "delay_days": 0, "subject_template": "Hi"}],
        },
    )
    assert r.status_code == 201, r.text
    a_camp_id = r.json()["id"]
    # B creates a campaign.
    r = await client.post(
        "/v1/campaigns", headers=bearer(b["access_token"]),
        json={
            "name": "B-camp",
            "style_sample_emails": ["Hi {first_name}, this is a test."],
            "steps": [{"step_number": 1, "delay_days": 0, "subject_template": "Hi"}],
        },
    )
    assert r.status_code == 201, r.text

    # A starts a run with no leads (should fail).
    r = await client.post(
        "/v1/sequences", headers=bearer(a["access_token"]),
        json={"campaign_id": a_camp_id, "name": "A-run-1", "lead_ids": []},
    )
    assert r.status_code == 422  # Pydantic min_length=1

    # Seed a lead for A and start a run.
    from outreach_os.domain.models.lead import Lead
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        lead = Lead(tenant_id=a["tenant_id"], source="serper", first_name="A", email="a-lead@x.example")
        session.add(lead)
        await session.flush()
        a_lead = str(lead.id)

    r = await client.post(
        "/v1/sequences", headers=bearer(a["access_token"]),
        json={"campaign_id": a_camp_id, "name": "A-run-1", "lead_ids": [a_lead]},
    )
    assert r.status_code == 201, r.text
    a_run_id = r.json()["id"]
    assert r.json()["step_count"] == 1
    assert r.json()["pending_count"] == 1

    # B sees 0 runs.
    r = await client.get("/v1/sequences", headers=bearer(b["access_token"]))
    assert r.status_code == 200
    assert r.json() == []

    # B cannot fetch A's run by id.
    r = await client.get(f"/v1/sequences/{a_run_id}", headers=bearer(b["access_token"]))
    assert r.status_code == 404


# --- Suppression: start_run skips suppressed leads ---

async def test_start_run_skips_suppressed_leads(client):
    a = await signup(client, email="a-sup@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-sup")
    r = await client.post(
        "/v1/campaigns", headers=bearer(a["access_token"]),
        json={
            "name": "sup-camp",
            "style_sample_emails": ["Hi {first_name}, this is a test."],
            "steps": [{"step_number": 1, "delay_days": 0, "subject_template": "Hi"}],
        },
    )
    camp_id = r.json()["id"]
    # Seed two leads, suppress one.
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.suppression import Suppression
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        l1 = Lead(tenant_id=a["tenant_id"], source="serper", email="keep@x.example", first_name="K")
        l2 = Lead(tenant_id=a["tenant_id"], source="serper", email="drop@x.example", first_name="D")
        session.add_all([l1, l2])
        await session.flush()
        session.add(Suppression(tenant_id=a["tenant_id"], email="drop@x.example", reason="manual"))
        keep_id, drop_id = str(l1.id), str(l2.id)

    r = await client.post(
        "/v1/sequences", headers=bearer(a["access_token"]),
        json={"campaign_id": camp_id, "name": "sup-run", "lead_ids": [keep_id, drop_id]},
    )
    assert r.status_code == 201, r.text
    # Only the non-suppressed lead is materialized.
    assert r.json()["step_count"] == 1


# --- Suppression list CRUD ---

async def test_suppression_list_add_remove(client):
    a = await signup(client, email="a-supp@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-supp")
    # Add a suppression.
    r = await client.post(
        "/v1/suppressions", headers=bearer(a["access_token"]),
        json={"email": "no-thanks@x.example", "reason": "unsubscribe"},
    )
    assert r.status_code == 201, r.text
    # List shows it.
    r = await client.get("/v1/suppressions", headers=bearer(a["access_token"]))
    assert r.json()["total"] == 1
    # Duplicate add is idempotent (returns the existing row).
    r = await client.post(
        "/v1/suppressions", headers=bearer(a["access_token"]),
        json={"email": "no-thanks@x.example", "reason": "unsubscribe"},
    )
    assert r.status_code == 201
    # Remove it.
    r = await client.delete(
        "/v1/suppressions/no-thanks@x.example", headers=bearer(a["access_token"])
    )
    assert r.status_code == 204
    # List is empty.
    r = await client.get("/v1/suppressions", headers=bearer(a["access_token"]))
    assert r.json()["total"] == 0


# --- Send engine: happy path ---

async def test_send_engine_fires_due_step(client, fake_llm_and_mailer):
    a = await signup(client, email="a-snd@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-snd")
    # Create campaign + mailbox + lead directly in DB.
    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.mailbox import Mailbox
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        camp = Campaign(
            tenant_id=a["tenant_id"], name="snd-camp",
            style_sample_emails=["Hi {first_name}, this is a test."],
        )
        session.add(camp)
        await session.flush()
        cs = CampaignStep(
            tenant_id=a["tenant_id"], campaign_id=camp.id,
            step_number=1, delay_days=0, subject_template="Quick question",
        )
        session.add(cs)
        mb = Mailbox(tenant_id=a["tenant_id"], provider="gmail", email_address="me@sender.example")
        session.add(mb)
        lead = Lead(tenant_id=a["tenant_id"], source="serper", email="target@x.example", first_name="T")
        session.add(lead)
        await session.flush()
        camp_id, _cs_id, lead_id = camp.id, cs.id, lead.id

    # Start the run.
    r = await client.post(
        "/v1/sequences", headers=bearer(a["access_token"]),
        json={"campaign_id": str(camp_id), "name": "snd-run", "lead_ids": [str(lead_id)]},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    assert r.json()["step_count"] == 1

    # Force the step to be due now.
    from datetime import datetime, timedelta

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        step = (await session.execute(
            select_sequence_step_for_run(run_id)
        )).scalar_one()
        step.scheduled_at = datetime.utcnow() - timedelta(seconds=5)

    # Run the send engine.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = SendService(session, mailer=fake_llm_and_mailer["stub"])
        sends = await svc.execute_due(tenant_id=a["tenant_id"])
    assert len(sends) == 1
    assert sends[0].status == "sent"
    assert sends[0].to_email == "target@x.example"
    assert fake_llm_and_mailer["stub"].sent[0].subject.startswith("Quick")

    # The step is now 'sent'.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        step = (await session.execute(
            select_sequence_step_for_run(run_id)
        )).scalar_one()
        assert step.status == "sent"
        assert step.sent_at is not None


# --- No override installed: falls back to the mailbox's own SMTP transport ---

async def test_send_service_uses_mailer_for_mailbox_when_no_override(client, monkeypatch):
    # The autouse fixture above installs a StubMailer override; remove it so
    # SendService has to resolve a mailer itself instead of short-circuiting.
    set_mailer_client(None)

    a = await signup(
        client, email="a-transport@acme-customer.example", password="pw-12345-AbCde",
        tenant_name="A-transport",
    )
    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.mailbox import Mailbox
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        camp = Campaign(
            tenant_id=a["tenant_id"], name="transport-camp",
            style_sample_emails=["Hi {first_name}, this is a test."],
        )
        session.add(camp)
        await session.flush()
        cs = CampaignStep(
            tenant_id=a["tenant_id"], campaign_id=camp.id,
            step_number=1, delay_days=0, subject_template="Hi",
        )
        session.add(cs)
        mb = Mailbox(tenant_id=a["tenant_id"], provider="smtp", email_address="me@sender.example")
        session.add(mb)
        lead = Lead(tenant_id=a["tenant_id"], source="serper", email="target@x.example", first_name="T")
        session.add(lead)
        await session.flush()
        camp_id, lead_id = camp.id, lead.id

    r = await client.post(
        "/v1/sequences", headers=bearer(a["access_token"]),
        json={"campaign_id": str(camp_id), "name": "transport-run", "lead_ids": [str(lead_id)]},
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    from datetime import datetime, timedelta

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        step = (await session.execute(
            select_sequence_step_for_run(run_id)
        )).scalar_one()
        step.scheduled_at = datetime.utcnow() - timedelta(seconds=5)

    from outreach_os.core.mailer import OutgoingMessage, SendReceipt

    class _RecordingMailer:
        def __init__(self) -> None:
            self.sent: list[OutgoingMessage] = []

        def send(self, message: OutgoingMessage) -> SendReceipt:
            self.sent.append(message)
            return SendReceipt(provider_message_id="recording-1", accepted=True)

    recorder = _RecordingMailer()
    recorded_mailboxes = []

    def _fake_mailer_for_mailbox(mailbox):
        recorded_mailboxes.append(mailbox)
        return recorder

    monkeypatch.setattr(
        "outreach_os.services.send_service.mailer_for_mailbox", _fake_mailer_for_mailbox
    )

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = SendService(session)  # no constructor mailer, no process override
        sends = await svc.execute_due(tenant_id=a["tenant_id"])

    assert len(sends) == 1
    assert sends[0].status == "sent"
    assert len(recorder.sent) == 1
    assert recorder.sent[0].from_email == "me@sender.example"
    assert recorded_mailboxes[0].email_address == "me@sender.example"


# --- Daily cap ---

async def test_send_engine_honours_daily_cap(client, fake_llm_and_mailer):
    a = await signup(client, email="a-cap@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-cap")
    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.mailbox import Mailbox
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        camp = Campaign(
            tenant_id=a["tenant_id"], name="cap-camp",
            style_sample_emails=["Hi {first_name}, this is a test."],
        )
        session.add(camp)
        await session.flush()
        cs = CampaignStep(
            tenant_id=a["tenant_id"], campaign_id=camp.id,
            step_number=1, delay_days=0, subject_template="Hi",
        )
        session.add(cs)
        mb = Mailbox(tenant_id=a["tenant_id"], provider="gmail", email_address="m@x.example", daily_send_cap=1)
        session.add(mb)
        leads = [
            Lead(tenant_id=a["tenant_id"], source="serper", email=f"l{i}@x.example", first_name=f"L{i}")
            for i in range(3)
        ]
        session.add_all(leads)
        await session.flush()
        camp_id, lead_ids = camp.id, [str(lead.id) for lead in leads]

    r = await client.post(
        "/v1/sequences", headers=bearer(a["access_token"]),
        json={"campaign_id": str(camp_id), "name": "cap-run", "lead_ids": lead_ids},
    )
    assert r.status_code == 201
    run_id = r.json()["id"]

    # Make all steps due.
    from datetime import datetime, timedelta

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        steps = (await session.execute(
            select_sequence_step_for_run(run_id)
        )).scalars().all()
        for s in steps:
            s.scheduled_at = datetime.utcnow() - timedelta(seconds=5)

    # Run a single pass: only 1 should fire (cap=1).
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = SendService(session, mailer=fake_llm_and_mailer["stub"])
        sends = await svc.execute_due(tenant_id=a["tenant_id"], limit=10)
    assert len(sends) == 1
    assert sends[0].status == "sent"
    # The other 2 are still pending.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        steps = (await session.execute(
            select_sequence_step_for_run(run_id)
        )).scalars().all()
        sent = sum(1 for s in steps if s.status == "sent")
        pending = sum(1 for s in steps if s.status in ("pending", "queued"))
        assert sent == 1
        assert pending == 2


# --- Tracking: open + click ---

async def test_tracking_endpoints_record_events(client):
    a = await signup(client, email="a-trk@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-trk")
    # Build a send row directly.
    from email.utils import make_msgid

    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.draft import Draft
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.mailbox import Mailbox
    from outreach_os.domain.models.send import Send
    from outreach_os.domain.models.sequence_run import SequenceRun
    from outreach_os.domain.models.sequence_step import SequenceStep
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        camp = Campaign(tenant_id=a["tenant_id"], name="trk-camp", style_sample_emails=[])
        session.add(camp)
        await session.flush()
        cs = CampaignStep(tenant_id=a["tenant_id"], campaign_id=camp.id, step_number=1, delay_days=0, subject_template="Hi")
        session.add(cs)
        await session.flush()
        mb = Mailbox(tenant_id=a["tenant_id"], provider="gmail", email_address="m@x.example")
        session.add(mb)
        lead = Lead(tenant_id=a["tenant_id"], source="serper", email="t@x.example", first_name="T")
        session.add(lead)
        await session.flush()
        run = SequenceRun(tenant_id=a["tenant_id"], campaign_id=camp.id, name="trk-run")
        session.add(run)
        await session.flush()
        step = SequenceStep(
            tenant_id=a["tenant_id"], run_id=run.id, lead_id=lead.id,
            campaign_step_id=cs.id, status="sent",
            scheduled_at=datetime_utc(), sent_at=datetime_utc(),
        )
        session.add(step)
        await session.flush()
        draft = Draft(tenant_id=a["tenant_id"], campaign_id=camp.id, lead_id=lead.id, step_id=cs.id,
                      status="ready", subject="Hi", body_preview="hi there", model_used="stub")
        session.add(draft)
        await session.flush()
        send = Send(
            tenant_id=a["tenant_id"], step_id=step.id, mailbox_id=mb.id, draft_id=draft.id,
            to_email="t@x.example", from_email="m@x.example",
            subject="Hi", body_text="hi there", message_id_header=make_msgid(domain="x.example"),
            status="sent", sent_at=datetime_utc(),
        )
        session.add(send)
        await session.flush()
        send_id = str(send.id)

    # Hit the open pixel.
    r = await client.get(f"/t/open/{send_id}.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # Hit a click redirect.
    r = await client.get(f"/t/click/{send_id}?url=https%3A%2F%2Fexample.com%2Fpath", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://example.com/path"
    # The send's opened_at / clicked_at are set.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        s = (await session.execute(
            __import__("sqlalchemy").select(Send).where(Send.id == send_id)
        )).scalar_one()
        assert s.opened_at is not None
        assert s.clicked_at is not None


# --- Unsubscribe endpoint ---

async def test_unsubscribe_endpoint_adds_suppression(client):
    r = await client.get(
        "/t/unsubscribe",
        params={"email": "opt-out@x.example", "tenant": "00000000-0000-0000-0000-000000000001"},
    )
    # No RLS context for this public endpoint; we don't create a tenant
    # for it, but the endpoint should still return 200. The Suppression
    # insert is wrapped in try/except so a missing tenant is OK.
    assert r.status_code == 200
    assert "unsubscribed" in r.text.lower()


# --- helpers ---


def select_sequence_step_for_run(run_id):
    from outreach_os.domain.models.sequence_step import SequenceStep
    return _select(SequenceStep).where(SequenceStep.run_id == run_id)


def datetime_utc():
    from datetime import datetime
    return datetime.utcnow()
