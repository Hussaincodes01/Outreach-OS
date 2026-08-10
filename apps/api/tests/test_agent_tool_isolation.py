"""The research tools must not put one lead's data into another's prompt.

`get_previous_touches` originally filtered on tenant alone, so the model was
shown the workspace's five most recent emails and told they were this lead's
history. That is both a correctness bug (inventing a relationship) and a
leak of one prospect's correspondence into another's draft.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.campaign import Campaign
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.models.draft import Draft
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.models.send import Send
from outreach_os.domain.models.sequence_run import SequenceRun
from outreach_os.domain.models.sequence_step import SequenceStep
from outreach_os.services.agent.tools import ToolContext, tool_by_name
from tests.conftest import signup, unique_email

pytestmark = pytest.mark.asyncio


async def _seed_two_leads_with_history(tenant_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Two leads in one workspace; only the second has been emailed."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, tenant_id)

        camp = Campaign(
            tenant_id=tenant_id, name="c", style_sample_emails=["Hi {first_name}."]
        )
        session.add(camp)
        await session.flush()
        cs = CampaignStep(
            tenant_id=tenant_id,
            campaign_id=camp.id,
            step_number=1,
            delay_days=0,
            subject_template="S",
        )
        mb = Mailbox(tenant_id=tenant_id, provider="gmail", email_address="m@x.example")
        session.add_all([cs, mb])

        quiet = Lead(tenant_id=tenant_id, source="serper", email="quiet@x.example")
        emailed = Lead(tenant_id=tenant_id, source="serper", email="emailed@x.example")
        session.add_all([quiet, emailed])
        await session.flush()

        run = SequenceRun(tenant_id=tenant_id, campaign_id=camp.id, name="r")
        session.add(run)
        await session.flush()
        step = SequenceStep(
            tenant_id=tenant_id,
            run_id=run.id,
            lead_id=emailed.id,
            campaign_step_id=cs.id,
            status="sent",
            scheduled_at=datetime.utcnow(),
            sent_at=datetime.utcnow(),
        )
        session.add(step)
        await session.flush()
        draft = Draft(
            tenant_id=tenant_id,
            campaign_id=camp.id,
            lead_id=emailed.id,
            step_id=cs.id,
            status="ready",
            subject="SECRET-OTHER-LEAD-SUBJECT",
            body_preview="hi",
            model_used="stub",
        )
        session.add(draft)
        await session.flush()
        session.add(
            Send(
                tenant_id=tenant_id,
                step_id=step.id,
                mailbox_id=mb.id,
                draft_id=draft.id,
                to_email="emailed@x.example",
                from_email="m@x.example",
                subject="SECRET-OTHER-LEAD-SUBJECT",
                body_text="hi",
                message_id_header="<a@x.example>",
                status="sent",
                sent_at=datetime.utcnow(),
            )
        )
        return quiet.id, emailed.id


def _ctx(session, tenant_id, lead_id) -> ToolContext:
    return ToolContext(
        session=session,
        tenant_id=uuid.UUID(str(tenant_id)),
        lead_id=lead_id,
        api_keys={},
    )


async def test_previous_touches_excludes_other_leads(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Touches",
    )
    tid = a["tenant_id"]
    quiet_id, emailed_id = await _seed_two_leads_with_history(tid)

    tool = tool_by_name("get_previous_touches")
    assert tool is not None

    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, tid)

        # The lead that was never emailed must have no history.
        quiet_out = await tool.run(_ctx(session, tid, quiet_id), {})
        assert "SECRET-OTHER-LEAD-SUBJECT" not in quiet_out, (
            "another lead's email leaked into this lead's research"
        )
        assert "No previous emails" in quiet_out

        # The lead that WAS emailed still sees its own history.
        emailed_out = await tool.run(_ctx(session, tid, emailed_id), {})
        assert "SECRET-OTHER-LEAD-SUBJECT" in emailed_out
