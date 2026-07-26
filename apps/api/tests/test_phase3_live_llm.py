"""Phase 3 — live LLM smoke test.

Runs the full pipeline against the real LiteLLM client. Skipped if
`OPENAI_API_KEY` is not set in the environment.

This is intentionally tiny — one happy-path generate — because real
LLM tests are slow and cost tokens. The deterministic fake covers
behavioural coverage; this one is a "does the wiring actually work
end-to-end with a real provider" check.
"""
from __future__ import annotations

import uuid

import pytest

from outreach_os.core.config import get_settings
from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import has_openai_key
from outreach_os.core.s3 import reset_for_tests
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.services.draft_service import DraftService
from tests.fake_llm import FakeLLMClient  # noqa: F401  (sanity import)

pytestmark = pytest.mark.live_llm


@pytest.fixture(autouse=True)
def _require_openai_key():
    if not has_openai_key():
        pytest.skip("OPENAI_API_KEY not set; skipping live LLM test")


async def test_live_generate_one_draft():
    """End-to-end with real LiteLLM. Cheap model (gpt-4o-mini)."""
    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.tenant import Tenant

    # Use a small model to keep cost minimal.
    settings = get_settings()
    settings.llm_default_model = "openai/gpt-4o-mini"

    factory = get_session_factory()
    tenant_id = uuid.uuid4()
    async with factory() as session, session.begin():
        t = Tenant(
            id=tenant_id,
            slug=f"live-{tenant_id.hex[:8]}",
            name="T-live",
            status="active",
            plan="starter",
        )
        session.add(t)
        await session.flush()
        await set_tenant_for_session(session, str(tenant_id))
        lead = Lead(
            tenant_id=tenant_id,
            source="serper",
            first_name="Sam",
            last_name="Carter",
            full_name="Sam Carter",
            email="sam@example.com",
            domain="example.com",
            company_name="Example Co",
            title="VP Sales",
        )
        session.add(lead)
        campaign = Campaign(
            tenant_id=tenant_id,
            name="live-camp",
            status="active",
            style_sample_emails=[
                "Hi {first_name}, noticed your team's growth. Worth a chat? Best, A"
            ],
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
        lead_id, campaign_id, step_id = lead.id, campaign.id, step.id

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = DraftService(session)  # use real LLM (not the fake)
        try:
            result = await svc.generate_draft(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                lead_id=lead_id,
                step_id=step_id,
            )
        finally:
            reset_for_tests()
        # Real LLMs occasionally refuse / content-filter; we accept
        # both "ready" and "failed" outcomes but require the call to
        # have produced SOMETHING.
        assert result.draft_id is not None
        assert result.status in ("ready", "failed")
        if result.status == "ready":
            assert result.subject
            assert result.body_preview
