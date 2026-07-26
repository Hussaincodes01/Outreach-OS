"""Phase 5 \u2014 Meeting booking + CRM sync tests.

Covers:
  - ICSBuilder produces a valid RFC 5545 string
  - MeetingService creates proposals, lists by status, declines
  - MeetingService confirm creates a real calendar event (StubCalendarClient)
  - MeetingService confirm rejects bad slot_index / wrong status
  - CrmService creates connections, syncs meetings to stub CRM
  - CrmService list_connections is RLS-isolated
  - Counter-reply positive classification auto-confirms an open proposal
  - First positive reply auto-creates a proposal
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from outreach_os.core.calendar_client import (
    CalendarEvent,
    ICSBuilder,
    StubCalendarClient,
    set_calendar_client,
)
from outreach_os.core.crm_client import StubCrmClient, set_crm_client
from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.tenant import Tenant
from outreach_os.services.meeting_service import MeetingError, MeetingService
from tests.conftest import bearer, signup


@pytest.fixture(autouse=True)
def fake_calendar_and_crm():
    cal = StubCalendarClient()
    set_calendar_client(cal)
    crm = StubCrmClient()
    set_crm_client(crm)
    yield {"calendar": cal, "crm": crm}
    set_calendar_client(None)
    set_crm_client(None)


async def _subscribe_growth(tenant_id) -> None:
    """Phase 7 plan gate: CRM sync is only on growth+. The phase 5
    tests predate billing — call this helper right after `signup` to
    subscribe the new tenant to growth so CRM sync assertions pass."""
    import uuid as _uuid
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    from outreach_os.core.db import get_session_factory
    from outreach_os.core.tenancy import set_tenant_for_session
    from outreach_os.services.billing_service import apply_subscription_event

    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        await apply_subscription_event(
            session,
            tenant_id=_uuid.UUID(str(tenant_id)),
            plan_code="growth",
            provider="stub",
            provider_customer_id="test_cust",
            provider_subscription_id="test_sub",
            status="active",
            current_period_start=_dt.now(_tz.utc),
            current_period_end=_dt.now(_tz.utc),
        )


# --- helpers ---


async def _ensure_tenant(tenant_id, slug: str, name: str) -> None:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        existing = await session.get(Tenant, tenant_id)
        if existing is None:
            session.add(
                Tenant(id=tenant_id, slug=slug, name=name,
                       plan="starter", status="active")
            )


async def _create_lead(tenant_id, email: str, first_name: str = "T") -> uuid.UUID:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, tenant_id)
        lead = Lead(
            tenant_id=tenant_id, source="serper",
            email=email, first_name=first_name,
        )
        session.add(lead)
        await session.flush()
        return lead.id


# --- ICSBuilder ---


def test_ics_builder_produces_valid_vcalendar():
    event = CalendarEvent(
        ics_uid="test-uid@x.example",
        subject="Test meeting",
        description="Discuss things",
        location="Google Meet",
        start=datetime(2030, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        end=datetime(2030, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
        organizer_email="me@x.example",
        attendee_emails=["you@x.example"],
        sequence=0,
        status="TENTATIVE",
    )
    payload = ICSBuilder.build(event)
    assert payload.startswith("BEGIN:VCALENDAR")
    assert "BEGIN:VEVENT" in payload
    assert "END:VEVENT" in payload
    assert "END:VCALENDAR" in payload
    assert "UID:test-uid@x.example" in payload
    assert "DTSTART:20300101T100000Z" in payload
    assert "DTEND:20300101T103000Z" in payload
    assert "STATUS:TENTATIVE" in payload
    assert "ORGANIZER;CN=Outreach OS:mailto:me@x.example" in payload
    assert "ATTENDEE;ROLE=REQ-PARTICIPIPANT:mailto:you@x.example" in payload


def test_ics_builder_escapes_commas_and_newlines():
    event = CalendarEvent(
        ics_uid="esc@x.example",
        subject="Hi, friend; please confirm",
        description="Line1\nLine2, with a comma",
        location=None,
        start=datetime(2030, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        end=datetime(2030, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
        organizer_email="me@x.example",
        attendee_emails=[],
        sequence=0,
        status="CONFIRMED",
    )
    payload = ICSBuilder.build(event)
    # comma + semicolon escaped
    assert "Hi\\, friend\\; please confirm" in payload
    # newline escaped
    assert "Line1\\nLine2\\, with a comma" in payload


# --- MeetingService ---


async def test_meeting_create_proposal_generates_three_slots(
    client
):
    a = await signup(
        client,
        email="a-prop@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-prop",
    )
    lead_id = await _create_lead(a["tenant_id"], "lead-prop@x.example")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = MeetingService(session)
        meeting = await svc.create_proposal(
            tenant_id=a["tenant_id"], lead_id=lead_id
        )
        assert meeting.status == "proposed"
        assert len(meeting.proposed_slots) == 3
        assert meeting.ics_uid.endswith("@outreach-os.local")
        assert meeting.organizer_email == "lead-prop@x.example"


async def test_meeting_confirm_creates_calendar_event(
    client, fake_calendar_and_crm
):
    a = await signup(
        client,
        email="a-conf@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-conf",
    )
    lead_id = await _create_lead(a["tenant_id"], "lead-conf@x.example")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = MeetingService(session)
        meeting = await svc.create_proposal(
            tenant_id=a["tenant_id"], lead_id=lead_id
        )
        confirmed = await svc.confirm(
            tenant_id=a["tenant_id"],
            meeting_id=meeting.id,
            slot_index=1,
        )
        assert confirmed.status == "confirmed"
        assert confirmed.chosen_slot is not None
        assert confirmed.confirmed_at is not None
        assert confirmed.provider_event_id is not None
        assert confirmed.provider_event_id.startswith("cal-stub-")
        assert confirmed.ics_sequence == 1

    # Stub calendar has the event
    cal = fake_calendar_and_crm["calendar"]
    assert len(cal.events) == 1
    ev = next(iter(cal.events.values()))
    assert ev.status == "CONFIRMED"
    assert ev.ics_uid.endswith("@outreach-os.local")


async def test_meeting_confirm_rejects_bad_slot(
    client
):
    a = await signup(
        client,
        email="a-bad@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-bad",
    )
    lead_id = await _create_lead(a["tenant_id"], "lead-bad@x.example")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = MeetingService(session)
        meeting = await svc.create_proposal(
            tenant_id=a["tenant_id"], lead_id=lead_id
        )
        with pytest.raises(MeetingError, match="slot_index"):
            await svc.confirm(
                tenant_id=a["tenant_id"],
                meeting_id=meeting.id,
                slot_index=99,
            )


async def test_meeting_decline_marks_status(
    client
):
    a = await signup(
        client,
        email="a-dec@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-dec",
    )
    lead_id = await _create_lead(a["tenant_id"], "lead-dec@x.example")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = MeetingService(session)
        meeting = await svc.create_proposal(
            tenant_id=a["tenant_id"], lead_id=lead_id
        )
        declined = await svc.decline(
            tenant_id=a["tenant_id"], meeting_id=meeting.id
        )
        assert declined.status == "declined"
        assert declined.declined_at is not None


async def test_meeting_list_isolated_per_tenant(client):
    a = await signup(
        client,
        email="a-iso@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-iso",
    )
    b = await signup(
        client,
        email="b-iso@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="B-iso",
    )
    a_lead = await _create_lead(a["tenant_id"], "la@x.example")
    b_lead = await _create_lead(b["tenant_id"], "lb@x.example")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = MeetingService(session)
        await svc.create_proposal(
            tenant_id=a["tenant_id"], lead_id=a_lead
        )
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, b["tenant_id"])
        svc = MeetingService(session)
        await svc.create_proposal(
            tenant_id=b["tenant_id"], lead_id=b_lead
        )
    # A only sees their meeting.
    r = await client.get("/v1/meetings", headers=bearer(a["access_token"]))
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    r = await client.get("/v1/meetings", headers=bearer(b["access_token"]))
    assert r.json()["total"] == 1


# --- CrmService ---


async def test_crm_connection_crud_isolated_per_tenant(client):
    a = await signup(
        client,
        email="a-crm@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-crm",
    )
    b = await signup(
        client,
        email="b-crm@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="B-crm",
    )
    # A creates a connection.
    r = await client.post(
        "/v1/crm/connections",
        headers=bearer(a["access_token"]),
        json={
            "provider": "google_sheets",
            "name": "A-Sheet",
            "spreadsheet_id": "sheet-A",
            "sheet_range": "Leads!A:D",
            "column_mapping": {
                "first_name": "A", "email": "B",
                "company_name": "C", "meeting_start": "D",
            },
        },
    )
    assert r.status_code == 201, r.text
    a_conn_id = r.json()["id"]

    # B creates their own connection.
    r = await client.post(
        "/v1/crm/connections",
        headers=bearer(b["access_token"]),
        json={
            "provider": "google_sheets",
            "name": "B-Sheet",
            "spreadsheet_id": "sheet-B",
        },
    )
    assert r.status_code == 201

    # A lists: only sees their own.
    r = await client.get("/v1/crm/connections", headers=bearer(a["access_token"]))
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["name"] == "A-Sheet"

    # B lists: only their own.
    r = await client.get("/v1/crm/connections", headers=bearer(b["access_token"]))
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["name"] == "B-Sheet"

    # A deletes.
    r = await client.delete(
        f"/v1/crm/connections/{a_conn_id}",
        headers=bearer(a["access_token"]),
    )
    assert r.status_code == 204
    r = await client.get("/v1/crm/connections", headers=bearer(a["access_token"]))
    assert r.json()["total"] == 0


async def test_crm_sync_meeting_writes_row_to_active_connections(
    client, fake_calendar_and_crm
):
    a = await signup(
        client,
        email="a-sync@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-sync",
    )
    await _subscribe_growth(a["tenant_id"])
    # Create a connection.
    r = await client.post(
        "/v1/crm/connections",
        headers=bearer(a["access_token"]),
        json={
            "provider": "google_sheets",
            "name": "A-Pipe",
            "spreadsheet_id": "sheet-pipe",
            "sheet_range": "Leads!A:D",
            "column_mapping": {
                "first_name": "A", "email": "B",
                "company_name": "C", "meeting_start": "D",
            },
        },
    )
    assert r.status_code == 201, r.text
    conn_id = r.json()["id"]
    # Create + confirm a meeting for the lead.
    lead_id = await _create_lead(a["tenant_id"], "lead-sync@x.example", "Sync")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = MeetingService(session)
        meeting = await svc.create_proposal(
            tenant_id=a["tenant_id"], lead_id=lead_id
        )
        confirmed = await svc.confirm(
            tenant_id=a["tenant_id"],
            meeting_id=meeting.id,
            slot_index=0,
        )
        meeting_id = confirmed.id

    # Sync manually.
    r = await client.post(
        f"/v1/crm/connections/{conn_id}/sync",
        params={"meeting_id": str(meeting_id)},
        headers=bearer(a["access_token"]),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "success"
    # The stub crm got one row with values in column order.
    crm = fake_calendar_and_crm["crm"]
    assert len(crm.rows) == 1
    row = crm.rows[0]
    assert row["spreadsheet_id"] == "sheet-pipe"
    # 4 columns: A=first_name, B=email, C=company_name, D=meeting_start
    assert len(row["values"]) == 4
    assert row["values"][0] == "Sync"      # first_name
    assert row["values"][1] == "lead-sync@x.example"  # email
    assert row["values"][3] != ""  # meeting_start is a real ISO

    # Listing sync events returns 1.
    r = await client.get(
        "/v1/crm/sync-events",
        params={"meeting_id": str(meeting_id)},
        headers=bearer(a["access_token"]),
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


async def test_crm_sync_meeting_records_failure_on_paused(
    client
):
    a = await signup(
        client,
        email="a-pause@acme-customer.example",
        password="pw-12345-AbCde",
        tenant_name="A-pause",
    )
    r = await client.post(
        "/v1/crm/connections",
        headers=bearer(a["access_token"]),
        json={
            "provider": "google_sheets",
            "name": "P",
            "spreadsheet_id": "s",
            "column_mapping": {"email": "A"},
        },
    )
    conn_id = r.json()["id"]
    # Pause the connection.
    r = await client.patch(
        f"/v1/crm/connections/{conn_id}",
        headers=bearer(a["access_token"]),
        json={"status": "paused"},
    )
    assert r.status_code == 200, r.text
    # Create + confirm a meeting.
    lead_id = await _create_lead(a["tenant_id"], "lp@x.example")
    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, a["tenant_id"])
        svc = MeetingService(session)
        meeting = await svc.create_proposal(
            tenant_id=a["tenant_id"], lead_id=lead_id
        )
        await svc.confirm(
            tenant_id=a["tenant_id"],
            meeting_id=meeting.id,
            slot_index=0,
        )
        meeting_id = meeting.id
    # Manual sync should be blocked (paused).
    r = await client.post(
        f"/v1/crm/connections/{conn_id}/sync",
        params={"meeting_id": str(meeting_id)},
        headers=bearer(a["access_token"]),
    )
    assert r.status_code == 400
    assert "paused" in r.text.lower()


# --- Counter-reply / first-reply hooks ---


async def test_first_positive_reply_creates_proposal(
    client
):
    """A positive reply on a Send with no open meeting should auto-create
    a proposal (3 slots, status=proposed) for the lead."""
    from outreach_os.core.llm import set_llm_client
    from tests.fake_llm import FakeLLMClient
    fake = FakeLLMClient()
    fake.next_reply_classification = ("positive", 0.95, "they want to chat")
    set_llm_client(fake)
    try:
        a = await signup(
            client,
            email="a-hook@acme-customer.example",
            password="pw-12345-AbCde",
            tenant_name="A-hook",
        )
        # Build a minimal campaign + mailbox + lead + send + reply chain.
        from datetime import datetime
        from email.utils import make_msgid

        from outreach_os.domain.models.campaign import Campaign
        from outreach_os.domain.models.campaign_step import CampaignStep
        from outreach_os.domain.models.draft import Draft
        from outreach_os.domain.models.mailbox import Mailbox
        from outreach_os.domain.models.send import Send
        from outreach_os.domain.models.sequence_run import SequenceRun
        from outreach_os.domain.models.sequence_step import SequenceStep
        lead_id = await _create_lead(a["tenant_id"], "lead-hook@x.example", "Hook")
        factory = get_session_factory()
        async with factory() as session, session.begin():
            await set_tenant_for_session(session, a["tenant_id"])
            camp = Campaign(
                tenant_id=a["tenant_id"], name="hook-camp",
                style_sample_emails=[],
            )
            session.add(camp)
            await session.flush()
            cs = CampaignStep(
                tenant_id=a["tenant_id"], campaign_id=camp.id,
                step_number=1, delay_days=0, subject_template="Hi",
            )
            session.add(cs)
            await session.flush()
            mb = Mailbox(
                tenant_id=a["tenant_id"], provider="gmail",
                email_address="h@x.example",
            )
            session.add(mb)
            run = SequenceRun(
                tenant_id=a["tenant_id"], campaign_id=camp.id,
                name="hook-run",
            )
            session.add(run)
            await session.flush()
            step = SequenceStep(
                tenant_id=a["tenant_id"], run_id=run.id, lead_id=lead_id,
                campaign_step_id=cs.id, status="sent",
                scheduled_at=datetime.utcnow(),
                sent_at=datetime.utcnow(),
            )
            session.add(step)
            await session.flush()
            draft = Draft(
                tenant_id=a["tenant_id"], campaign_id=camp.id,
                lead_id=lead_id, step_id=cs.id,
                status="ready", subject="Hi",
                body_preview="body", model_used="stub",
            )
            session.add(draft)
            await session.flush()
            mid = make_msgid(domain="x.example")
            send = Send(
                tenant_id=a["tenant_id"], step_id=step.id,
                mailbox_id=mb.id, draft_id=draft.id,
                to_email="lead-hook@x.example", from_email="h@x.example",
                subject="Hi", body_text="body",
                message_id_header=mid,
                status="sent", sent_at=datetime.utcnow(),
            )
            session.add(send)
            await session.flush()
        import hashlib
        import hmac

        from outreach_os.core.config import get_settings
        settings = get_settings()
        webhook_secret = settings.inbound_webhook_secret or "test-webhook-secret"
        payload = {
            "message_id_header": make_msgid(domain="y.example"),
            "from_email": "lead-hook@x.example",
            "from_name": "Hook",
            "subject": "Re: Hi",
            "body_text": "Sure, let's chat. Book a meeting.",
            "in_reply_to": mid,
        }
        # Use compact JSON to match FastAPI test client encoding
        body = json.dumps(payload, separators=(',', ':'))
        sig = hmac.new(
            webhook_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {"X-Outreach-Signature": sig}

        # POST a positive reply via the webhook.
        r = await client.post(
            "/v1/webhooks/inbound-email",
            json=payload,
            headers=headers,
        )
        assert r.status_code == 202, r.text

        # A meeting was created, status=proposed, 3 slots.
        r = await client.get("/v1/meetings", headers=bearer(a["access_token"]))
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        m = data["items"][0]
        assert m["status"] == "proposed"
        assert len(m["proposed_slots"]) == 3
    finally:
        set_llm_client(None)


async def test_counter_reply_positive_auto_confirms_open_proposal(
    client
):
    """A second positive reply for the same lead should auto-confirm the
    open proposal (slot 0) and trigger a CRM sync (if any connection
    is active)."""
    from outreach_os.core.llm import set_llm_client
    from tests.fake_llm import FakeLLMClient
    fake = FakeLLMClient()
    fake.next_reply_classification = ("positive", 0.9, "first reply sets up meeting")
    set_llm_client(fake)
    try:
        a = await signup(
            client,
            email="a-cnt@acme-customer.example",
            password="pw-12345-AbCde",
            tenant_name="A-cnt",
        )
        await _subscribe_growth(a["tenant_id"])
        # Set up an active CRM connection to verify the auto-sync.
        r = await client.post(
            "/v1/crm/connections",
            headers=bearer(a["access_token"]),
            json={
                "provider": "google_sheets",
                "name": "C",
                "spreadsheet_id": "s",
                "column_mapping": {"email": "A", "meeting_start": "B"},
            },
        )
        assert r.status_code == 201

        # Create a pre-existing open meeting for the lead.
        lead_id = await _create_lead(a["tenant_id"], "lc@x.example", "Cnt")
        async with get_session_factory()() as session, session.begin():
            await set_tenant_for_session(session, a["tenant_id"])
            svc = MeetingService(session)
            pre_meeting = await svc.create_proposal(
                tenant_id=a["tenant_id"], lead_id=lead_id
            )
            pre_meeting_id = pre_meeting.id

        # Now ingest a positive reply (counter-reply case).
        from datetime import datetime
        from email.utils import make_msgid

        from outreach_os.domain.models.campaign import Campaign
        from outreach_os.domain.models.campaign_step import CampaignStep
        from outreach_os.domain.models.draft import Draft
        from outreach_os.domain.models.mailbox import Mailbox
        from outreach_os.domain.models.send import Send
        from outreach_os.domain.models.sequence_run import SequenceRun
        from outreach_os.domain.models.sequence_step import SequenceStep
        factory = get_session_factory()
        mid = make_msgid(domain="x.example")
        async with factory() as session, session.begin():
            await set_tenant_for_session(session, a["tenant_id"])
            camp = Campaign(
                tenant_id=a["tenant_id"], name="cnt-camp",
                style_sample_emails=[],
            )
            session.add(camp)
            await session.flush()
            cs = CampaignStep(
                tenant_id=a["tenant_id"], campaign_id=camp.id,
                step_number=1, delay_days=0, subject_template="Hi",
            )
            session.add(cs)
            await session.flush()
            mb = Mailbox(
                tenant_id=a["tenant_id"], provider="gmail",
                email_address="c@x.example",
            )
            session.add(mb)
            run = SequenceRun(
                tenant_id=a["tenant_id"], campaign_id=camp.id,
                name="cnt-run",
            )
            session.add(run)
            await session.flush()
            step = SequenceStep(
                tenant_id=a["tenant_id"], run_id=run.id, lead_id=lead_id,
                campaign_step_id=cs.id, status="sent",
                scheduled_at=datetime.utcnow(),
                sent_at=datetime.utcnow(),
            )
            session.add(step)
            await session.flush()
            draft = Draft(
                tenant_id=a["tenant_id"], campaign_id=camp.id,
                lead_id=lead_id, step_id=cs.id,
                status="ready", subject="Hi",
                body_preview="body", model_used="stub",
            )
            session.add(draft)
            await session.flush()
            send = Send(
                tenant_id=a["tenant_id"], step_id=step.id,
                mailbox_id=mb.id, draft_id=draft.id,
                to_email="lc@x.example", from_email="c@x.example",
                subject="Hi", body_text="body",
                message_id_header=mid,
                status="sent", sent_at=datetime.utcnow(),
            )
            session.add(send)
            await session.flush()

        # Reply (counter-reply).
        import hashlib
        import hmac

        from outreach_os.core.config import get_settings
        settings = get_settings()
        webhook_secret = settings.inbound_webhook_secret or "test-webhook-secret"
        payload2 = {
            "message_id_header": make_msgid(domain="z.example"),
            "from_email": "lc@x.example",
            "subject": "Re: Hi",
            "body_text": "Yes, Tuesday at 2pm works!",
            "in_reply_to": mid,
        }
        # Use compact JSON to match FastAPI test client encoding
        body2 = json.dumps(payload2, separators=(',', ':'))
        sig2 = hmac.new(
            webhook_secret.encode("utf-8"),
            body2.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers2 = {"X-Outreach-Signature": sig2}

        r = await client.post(
            "/v1/webhooks/inbound-email",
            json=payload2,
            headers=headers2,
        )
        assert r.status_code == 202, r.text

        # The pre-existing meeting is now confirmed.
        r = await client.get(
            f"/v1/meetings/{pre_meeting_id}",
            headers=bearer(a["access_token"]),
        )
        assert r.status_code == 200
        m = r.json()
        assert m["status"] == "confirmed"
        assert m["chosen_slot"] is not None
        assert m["provider_event_id"] is not None

        # A CRM sync event was recorded (auto-sync after confirm).
        r = await client.get(
            "/v1/crm/sync-events",
            headers=bearer(a["access_token"]),
        )
        assert r.status_code == 200
        sync_data = r.json()
        assert sync_data["total"] == 1
        assert sync_data["items"][0]["status"] == "success"
    finally:
        set_llm_client(None)
