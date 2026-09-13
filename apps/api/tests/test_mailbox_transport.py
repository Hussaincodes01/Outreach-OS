"""Sequence sends use the sending mailbox's SMTP settings, and run on schedule."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from outreach_os.core.llm import set_llm_client
from outreach_os.core.mailer import SmtpMailer, get_mailer_override, set_mailer_client
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.services import vault_service
from outreach_os.services.local_workspace import LOCAL_TENANT_ID
from outreach_os.services.mailbox.transport import mailer_for_mailbox
from outreach_os.services.send_service import SendService
from outreach_os.workers.celery_app import celery_app
from tests.fake_llm import FakeLLMClient


def _smtp_mailbox() -> Mailbox:
    cfg = {"host": "smtp.example.org", "port": 587, "username": "me", "password": "pw", "use_tls": True}
    return Mailbox(
        id=uuid.uuid4(),
        tenant_id=LOCAL_TENANT_ID,
        provider="smtp",
        email_address="me@example.org",
        smtp_config_ciphertext=vault_service.encrypt_for_tenant(str(LOCAL_TENANT_ID), cfg),
    )


def test_mailer_for_smtp_mailbox_uses_its_settings() -> None:
    mailer = mailer_for_mailbox(_smtp_mailbox())
    assert isinstance(mailer, SmtpMailer)
    assert mailer._host == "smtp.example.org"
    assert mailer._port == 587
    assert mailer._username == "me"
    assert mailer._default_from == "me@example.org"


def test_override_is_none_until_set() -> None:
    set_mailer_client(None)
    assert get_mailer_override() is None


def test_send_due_is_on_beat_schedule() -> None:
    tasks = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert "outreach_os.workers.send_due" in tasks


async def test_gmail_oauth_routes_are_gone(client) -> None:
    assert (await client.get("/v1/mailboxes/oauth/gmail/start")).status_code == 404
    assert (await client.get("/v1/mailboxes/oauth/outlook/start")).status_code == 404


async def test_decrypt_failure_marks_send_failed_without_crashing_batch(scoped_session) -> None:
    """A mailbox whose SMTP config can't be decrypted must fail just that
    send (via the existing MailerError failure branch), never raise out of
    execute_due and abort the rest of the batch."""
    set_llm_client(FakeLLMClient())
    set_mailer_client(None)  # force SendService to resolve mailer_for_mailbox

    from outreach_os.domain.models.campaign import Campaign
    from outreach_os.domain.models.campaign_step import CampaignStep
    from outreach_os.domain.models.lead import Lead
    from outreach_os.domain.models.sequence_run import SequenceRun
    from outreach_os.domain.models.sequence_step import SequenceStep

    session = scoped_session
    camp = Campaign(
        tenant_id=LOCAL_TENANT_ID, name="broken-mailbox-camp",
        style_sample_emails=["Hi {first_name}, this is a test."],
    )
    session.add(camp)
    await session.flush()
    cs = CampaignStep(
        tenant_id=LOCAL_TENANT_ID, campaign_id=camp.id,
        step_number=1, delay_days=0, subject_template="Hi",
    )
    session.add(cs)
    # SMTP provider but no stored config at all -> smtp_config() raises MailError.
    mb = Mailbox(tenant_id=LOCAL_TENANT_ID, provider="smtp", email_address="broken@sender.example")
    session.add(mb)
    lead = Lead(tenant_id=LOCAL_TENANT_ID, source="serper", email="target@x.example", first_name="T")
    session.add(lead)
    await session.flush()
    run = SequenceRun(tenant_id=LOCAL_TENANT_ID, campaign_id=camp.id, name="broken-run")
    session.add(run)
    await session.flush()
    step = SequenceStep(
        tenant_id=LOCAL_TENANT_ID, run_id=run.id, lead_id=lead.id,
        campaign_step_id=cs.id, status="pending",
        scheduled_at=datetime.utcnow() - timedelta(seconds=5),
    )
    session.add(step)
    await session.flush()

    svc = SendService(session)
    sends = await svc.execute_due(tenant_id=LOCAL_TENANT_ID)

    assert len(sends) == 1
    assert sends[0].status == "failed"
    assert step.status == "failed"
    assert "SMTP" in (step.stop_reason or "") or "smtp" in (step.stop_reason or "").lower()

    set_llm_client(None)
