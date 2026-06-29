"""Phase 3 — draft pipeline tests with a deterministic fake LLM.

Verifies the full LangGraph pipeline (research -> niche -> style -> draft)
runs end-to-end against the test DB and produces a Draft row + an
AgentRun row, with the body stored in S3. Tests do NOT require a real
LLM key.
"""
from __future__ import annotations

import uuid

import pytest

from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import set_llm_client
from outreach_os.core.s3 import reset_for_tests
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.services.draft_service import DraftService
from tests.conftest import bearer, signup
from tests.fake_llm import FakeLLMClient


@pytest.fixture(autouse=True)
def _fake_llm():
    fake = FakeLLMClient()
    set_llm_client(fake)
    yield fake
    set_llm_client(None)
    reset_for_tests()


async def test_draft_pipeline_proces_lead_and_step(_fake_llm):
    """End-to-end: tenant + campaign + step + lead → run generate_draft →
    a 'ready' Draft row exists with subject + body_preview, and an
    AgentRun row records the trace + tokens."""
    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    # We need to seed: tenant, icp, lead, campaign, step.
    # Rather than hit the HTTP API, use the DB directly so the test is
    # tightly scoped to the pipeline logic.
    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.icp import Icp
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.tenant import Tenant
    from outreach_os.domain.models.user import AppUser, UserRole

    async with factory() as session:
        async with session.begin():
            # Insert the tenant (no RLS on tenant). Then set RLS and
            # insert the rest in the same session/transaction.
            t = Tenant(id=tenant_id, slug=f"t-{tenant_id.hex[:8]}", name="T-pipe", status="active", plan="starter")
            session.add(t)
            await session.flush()
            await set_tenant_for_session(session, str(tenant_id))
            u = AppUser(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                email=f"u-{tenant_id.hex[:8]}@example.com",
                role=UserRole.OWNER.value,
                password_hash="x",
            )
            session.add(u)
            icp = Icp(tenant_id=tenant_id, name="ICP-1", is_active=True)
            session.add(icp)
            await session.flush()
            lead = Lead(
                tenant_id=tenant_id,
                source="serper",
                first_name="Alex",
                last_name="Doe",
                full_name="Alex Doe",
                email="alex@example.com",
                domain="example.com",
                company_name="Example Co",
                title="VP Sales",
            )
            session.add(lead)
            campaign = Campaign(
                tenant_id=tenant_id,
                name="C-1",
                status="active",
                style_sample_emails=[
                    "Hi {first_name}, short and direct. Best, Me"
                ],
                style_notes="Avoid fluff.",
            )
            session.add(campaign)
            await session.flush()
            step = CampaignStep(
                tenant_id=tenant_id,
                campaign_id=campaign.id,
                step_number=1,
                delay_days=0,
                subject_template="Quick question",
                goal="open a conversation",
            )
            session.add(step)
            await session.flush()
            campaign_id = campaign.id
            lead_id = lead.id
            step_id = step.id

    # Now run the pipeline.
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            svc = DraftService(session, llm=_fake_llm)
            result = await svc.generate_draft(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                lead_id=lead_id,
                step_id=step_id,
            )
            assert result.status == "ready"
            assert result.subject
            assert result.body_preview
            assert result.model_used
            draft_id = result.draft_id
            run_id = result.agent_run_id

    # Verify rows in fresh session.
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            from sqlalchemy import select
            from outreach_os.domain.models.agent_run import AgentRun
            from outreach_os.domain.models.draft import Draft

            d = (
                await session.execute(
                    select(Draft).where(Draft.tenant_id == tenant_id)
                )
            ).scalar_one()
            assert d.id == draft_id
            assert d.status == "ready"
            assert d.subject
            assert d.body_preview
            assert d.model_used

            r = (
                await session.execute(
                    select(AgentRun).where(AgentRun.tenant_id == tenant_id)
                )
            ).scalar_one()
            assert r.id == run_id
            assert r.status == "completed"
            assert r.input_tokens > 0
            assert r.output_tokens > 0
            # The trace should mention all four nodes.
            assert "research" in r.trace
            assert "niche" in r.trace
            assert "style" in r.trace
            assert "draft" in r.trace


async def test_draft_idempotent_within_same_lead_step(_fake_llm):
    """Re-running generation for the same (campaign, lead, step) without
    `force_regenerate` returns the existing draft, not a new one."""
    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.tenant import Tenant

    async with factory() as session:
        async with session.begin():
            t = Tenant(id=tenant_id, slug=f"i-{tenant_id.hex[:8]}", name="T-idem", status="active", plan="starter")
            session.add(t)
            await session.flush()
            await set_tenant_for_session(session, str(tenant_id))
            lead = Lead(tenant_id=tenant_id, source="serper", first_name="A", email="a@x.com")
            session.add(lead)
            campaign = Campaign(tenant_id=tenant_id, name="C-idem", status="active")
            session.add(campaign)
            await session.flush()
            step = CampaignStep(tenant_id=tenant_id, campaign_id=campaign.id, step_number=1, delay_days=0, subject_template="S")
            session.add(step)
            await session.flush()
            lead_id, campaign_id, step_id = lead.id, campaign.id, step.id

    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            svc = DraftService(session, llm=_fake_llm)
            r1 = await svc.generate_draft(
                tenant_id=tenant_id, campaign_id=campaign_id,
                lead_id=lead_id, step_id=step_id,
            )
            r2 = await svc.generate_draft(
                tenant_id=tenant_id, campaign_id=campaign_id,
                lead_id=lead_id, step_id=step_id,
            )
            assert r1.draft_id == r2.draft_id
            assert r1.status == r2.status == "ready"


async def test_force_regenerate_replaces_draft(_fake_llm):
    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.tenant import Tenant

    async with factory() as session:
        async with session.begin():
            session.add(Tenant(id=tenant_id, slug=f"f-{tenant_id.hex[:8]}", name="T-fr", status="active", plan="starter"))
            await session.flush()
            await set_tenant_for_session(session, str(tenant_id))
            lead = Lead(tenant_id=tenant_id, source="serper", first_name="A", email="a@x.com")
            session.add(lead)
            campaign = Campaign(tenant_id=tenant_id, name="C-fr", status="active")
            session.add(campaign)
            await session.flush()
            step = CampaignStep(tenant_id=tenant_id, campaign_id=campaign.id, step_number=1, delay_days=0, subject_template="S")
            session.add(step)
            await session.flush()
            lead_id, campaign_id, step_id = lead.id, campaign.id, step.id

    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, str(tenant_id))
            svc = DraftService(session, llm=_fake_llm)
            r1 = await svc.generate_draft(
                tenant_id=tenant_id, campaign_id=campaign_id,
                lead_id=lead_id, step_id=step_id,
            )
            r2 = await svc.generate_draft(
                tenant_id=tenant_id, campaign_id=campaign_id,
                lead_id=lead_id, step_id=step_id,
                force_regenerate=True,
            )
            assert r1.draft_id != r2.draft_id
            assert r2.status == "ready"


async def test_draft_status_filter_and_pagination_via_api(_fake_llm, client):
    """Smoke test the GET /v1/drafts endpoint after a generation."""
    a = await signup(client, email="drafts-list@acme-customer.example", password="pw-12345-AbCde", tenant_name="DraftsList")
    # Seed: campaign + lead + step.
    r = await client.post(
        "/v1/campaigns",
        headers=bearer(a["access_token"]),
        json={
            "name": "drafts-list-camp",
            "style_sample_emails": ["Hi {first_name}, this is a test email body."],
            "steps": [{"step_number": 1, "delay_days": 0, "subject_template": "Quick question"}],
        },
    )
    assert r.status_code == 201, r.text
    campaign_id = r.json()["id"]
    step_id = r.json()["steps"][0]["id"]

    # Need a lead. Easiest: create one directly via the leads endpoint? We
    # don't have a "create lead" endpoint. Seed via DB.
    from outreach_os.core.db import get_session_factory
    from outreach_os.core.tenancy import set_tenant_for_session
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            await set_tenant_for_session(session, a["tenant_id"])
            from outreach_os.domain.models.lead import Lead
            lead = Lead(tenant_id=uuid.UUID(a["tenant_id"]), source="serper",
                        first_name="A", email="a@x.com")
            session.add(lead)
            await session.flush()
            lead_id = str(lead.id)

    # Generate the draft.
    r = await client.post(
        "/v1/drafts/generate",
        headers=bearer(a["access_token"]),
        json={"lead_id": lead_id, "step_id": step_id},
    )
    assert r.status_code == 200, r.text
    draft_id = r.json()["id"]

    # List drafts.
    r = await client.get(
        f"/v1/drafts?campaign_id={campaign_id}", headers=bearer(a["access_token"])
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["status"] == "ready"

    # Filter by status.
    r = await client.get(
        "/v1/drafts?status=approved", headers=bearer(a["access_token"])
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # Approve the draft.
    r = await client.patch(
        f"/v1/drafts/{draft_id}",
        headers=bearer(a["access_token"]),
        json={"status": "approved"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
