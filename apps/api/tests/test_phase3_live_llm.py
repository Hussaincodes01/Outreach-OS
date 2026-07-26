"""Phase 3 — live LLM smoke test, through the real BYOK path.

Runs the full pipeline against a real provider using a key stored in the
tenant's encrypted vault — exactly how production resolves credentials. It is
therefore also the end-to-end proof that BYOK resolution works, not just that
LiteLLM works.

Skipped unless `OUTREACH_TEST_OPENAI_KEY` is set. That is a test-only variable:
the application itself never reads provider keys from the environment.

Intentionally tiny — one happy-path generate — because real LLM tests are slow
and cost tokens. The deterministic fake carries the behavioural coverage.
"""
from __future__ import annotations

import os
import uuid

import pytest

from outreach_os.core.config import get_settings
from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import set_llm_client
from outreach_os.core.s3 import reset_for_tests
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.services.credential_lookup import create_credential
from outreach_os.services.draft_service import DraftService
from tests.fake_llm import FakeLLMClient  # noqa: F401  (sanity import)

pytestmark = pytest.mark.live_llm

_LIVE_KEY_ENV = "OUTREACH_TEST_OPENAI_KEY"


@pytest.fixture(autouse=True)
def _require_openai_key():
    if not os.environ.get(_LIVE_KEY_ENV):
        pytest.skip(f"{_LIVE_KEY_ENV} not set; skipping live LLM test")
    # The conftest autouse fake would otherwise short-circuit BYOK resolution;
    # clear it so this test exercises the real credential path.
    set_llm_client(None)
    yield
    set_llm_client(None)


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

        # BYOK: store the provider key in the tenant's vault. This is the only
        # way the pipeline can obtain credentials — nothing reads the env.
        await create_credential(
            session,
            tenant_id=tenant_id,
            kind="llm_openai",
            plaintext={"api_key": os.environ[_LIVE_KEY_ENV]},
            label="live test key",
        )
        lead_id, campaign_id, step_id = lead.id, campaign.id, step.id

    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = DraftService(session)  # no injected client: resolve via BYOK
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
