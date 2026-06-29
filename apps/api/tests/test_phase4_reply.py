"""Phase 4 — ReplyService: classification + side effects."""
from __future__ import annotations

import pytest

from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import set_llm_client
from outreach_os.core.mailer import StubMailer, set_mailer_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.send import Send
from outreach_os.domain.models.sequence_run import SequenceRun
from outreach_os.domain.models.sequence_step import SequenceStep
from outreach_os.domain.models.suppression import Suppression
from outreach_os.domain.models.campaign import Campaign
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.models.draft import Draft
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.schemas.phase4 import ReplyIngestIn
from outreach_os.services.reply_service import ReplyService
from tests.fake_llm import FakeLLMClient


@pytest.fixture(autouse=True)
def _fake_llm():
    """Deterministic fake that returns the classification we want by
    matching the body text we send in."""
    from outreach_os.core.llm import LLMResponse, LLMUsage
    class StubClassifier(FakeLLMClient):
        def chat(self, model, messages, **kwargs):
            text = messages[-1]["content"] if messages else ""
            if "yes, let's chat" in text.lower():
                cls = "positive"
            elif "not interested" in text.lower():
                cls = "negative"
            elif "out of office" in text.lower():
                cls = "ooo"
            elif "please remove" in text.lower():
                cls = "unsubscribe"
            else:
                cls = "other"
            import json
            return LLMResponse(
                text=json.dumps({"classification": cls, "confidence": 0.9, "reason": "matched"}),
                usage=LLMUsage(input_tokens=100, output_tokens=50),
            )
    fake = StubClassifier()
    set_llm_client(fake)
    set_mailer_client(StubMailer())
    yield fake
    set_llm_client(None)
    set_mailer_client(None)


async def _seed(tenant_id) -> dict:
    """Build a campaign + mailbox + lead + 2-step sequence with one step sent."""
    import uuid as _u
    from datetime import datetime
    factory = get_session_factory()
    # Step 1: ensure tenant exists (no RLS, no GUC).
    async with factory() as session:
        async with session.begin():
            existing = await session.get(Tenant, tenant_id)
            if existing is None:
                session.add(Tenant(id=tenant_id, slug=f"r-{_u.uuid4().hex[:6]}", name="r", plan="starter", status="active"))
    # Step 2: set GUC, then insert RLS-protected rows.
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            camp = Campaign(tenant_id=tenant_id, name="reply-camp", style_sample_emails=["Hi {first_name}."])
            session.add(camp); await session.flush()
            cs1 = CampaignStep(tenant_id=tenant_id, campaign_id=camp.id, step_number=1, delay_days=0, subject_template="S1")
            cs2 = CampaignStep(tenant_id=tenant_id, campaign_id=camp.id, step_number=2, delay_days=3, subject_template="S2")
            session.add_all([cs1, cs2]); await session.flush()
            mb = Mailbox(tenant_id=tenant_id, provider="gmail", email_address="m@x.example")
            session.add(mb)
            lead = Lead(tenant_id=tenant_id, source="serper", email="lead@x.example", first_name="L")
            session.add(lead); await session.flush()
            run = SequenceRun(tenant_id=tenant_id, campaign_id=camp.id, name="reply-run")
            session.add(run); await session.flush()
            step1 = SequenceStep(
                tenant_id=tenant_id, run_id=run.id, lead_id=lead.id, campaign_step_id=cs1.id,
                status="sent", scheduled_at=datetime.utcnow(), sent_at=datetime.utcnow(),
            )
            step2 = SequenceStep(
                tenant_id=tenant_id, run_id=run.id, lead_id=lead.id, campaign_step_id=cs2.id,
                status="pending", scheduled_at=datetime.utcnow(),
            )
            session.add_all([step1, step2]); await session.flush()
            draft = Draft(
                tenant_id=tenant_id, campaign_id=camp.id, lead_id=lead.id, step_id=cs1.id,
                status="ready", subject="S1", body_preview="hi", model_used="stub",
            )
            session.add(draft); await session.flush()
            from email.utils import make_msgid
            send = Send(
                tenant_id=tenant_id, step_id=step1.id, mailbox_id=mb.id, draft_id=draft.id,
                to_email="lead@x.example", from_email="m@x.example",
                subject="S1", body_text="hi", message_id_header=make_msgid(domain="x.example"),
                status="sent", sent_at=datetime.utcnow(),
            )
            session.add(send); await session.flush()
            return {
                "run_id": run.id, "step1_id": step1.id, "step2_id": step2.id,
                "send_id": send.id, "message_id": send.message_id_header,
                "lead_id": lead.id,
            }


async def test_reply_classifier_stops_on_positive():
    tid = __import__("uuid").UUID("00000000-0000-0000-0000-000000000101")
    ids = await _seed(tid)
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tid))
            svc = ReplyService(session)
            reply = await svc.ingest(
                tenant_id=tid,
                data=ReplyIngestIn(
                    message_id_header="<inreply-1@x.example>",
                    from_email="lead@x.example",
                    in_reply_to=ids["message_id"],
                    references=ids["message_id"],
                    body_text="Yes, let's chat! When works for you?",
                ),
            )
    assert reply is not None
    assert reply.classification == "positive"
    # The run's step1 -> replied, step2 -> stopped.
    from sqlalchemy import select
    from outreach_os.domain.models.sequence_step import SequenceStep
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tid))
            steps = (await session.execute(
                select(SequenceStep).where(SequenceStep.run_id == ids["run_id"])
            )).scalars().all()
            statuses = {s.id: s.status for s in steps}
            assert statuses[ids["step1_id"]] == "replied"
            assert statuses[ids["step2_id"]] == "stopped"
            # positive does NOT auto-suppress.
            sup = (await session.execute(
                select(Suppression).where(Suppression.email == "lead@x.example")
            )).scalar_one_or_none()
            assert sup is None


async def test_reply_classifier_adds_suppression_on_unsubscribe():
    tid = __import__("uuid").UUID("00000000-0000-0000-0000-000000000102")
    ids = await _seed(tid)
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tid))
            svc = ReplyService(session)
            await svc.ingest(
                tenant_id=tid,
                data=ReplyIngestIn(
                    message_id_header="<inreply-2@x.example>",
                    from_email="lead@x.example",
                    in_reply_to=ids["message_id"],
                    references=ids["message_id"],
                    body_text="Please remove me from your list immediately.",
                ),
            )
    from sqlalchemy import select
    from outreach_os.domain.models.sequence_step import SequenceStep
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tid))
            sup = (await session.execute(
                select(Suppression).where(Suppression.email == "lead@x.example")
            )).scalar_one_or_none()
            assert sup is not None
            assert sup.reason == "unsubscribe"
            # Step2 was stopped.
            s2 = await session.get(SequenceStep, ids["step2_id"])
            assert s2.status == "stopped"
            assert "unsubscribe" in (s2.stop_reason or "")


async def test_reply_dedup():
    tid = __import__("uuid").UUID("00000000-0000-0000-0000-000000000103")
    ids = await _seed(tid)
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tid))
            svc = ReplyService(session)
            r1 = await svc.ingest(
                tenant_id=tid,
                data=ReplyIngestIn(
                    message_id_header="<dup@x.example>",
                    from_email="lead@x.example",
                    in_reply_to=ids["message_id"],
                    references=ids["message_id"],
                    body_text="Sounds great, count me in.",
                ),
            )
    # Second ingest with the same message_id_header is a no-op.
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tid))
            svc = ReplyService(session)
            r2 = await svc.ingest(
                tenant_id=tid,
                data=ReplyIngestIn(
                    message_id_header="<dup@x.example>",
                    from_email="lead@x.example",
                    in_reply_to=ids["message_id"],
                    references=ids["message_id"],
                    body_text="Sounds great, count me in.",
                ),
            )
    assert r1 is not None
    assert r2 is None  # dedup


async def test_reply_for_unknown_send_is_silently_dropped():
    tid = __import__("uuid").UUID("00000000-0000-0000-0000-000000000104")
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tid))
            svc = ReplyService(session)
            r = await svc.ingest(
                tenant_id=tid,
                data=ReplyIngestIn(
                    message_id_header="<orphan@x.example>",
                    from_email="nobody@x.example",
                    in_reply_to="<unknown-msgid@x.example>",
                    references="",
                    body_text="Hello?",
                ),
            )
    assert r is None
