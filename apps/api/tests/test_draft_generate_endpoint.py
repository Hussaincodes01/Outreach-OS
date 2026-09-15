"""POST /v1/drafts/generate must return a real draft in the deployed stack.

The compose stack runs Celery with `CELERY_TASK_ALWAYS_EAGER=false`. The
endpoint used to enqueue the pipeline and answer with a placeholder whose
`draft_id` was a random UUID, then look that id up and fail with
"draft not found after generation" (HTTP 500) on every call. The suite runs
eagerly, so only the deployed configuration hit it.
"""
from __future__ import annotations

import uuid

import pytest

from outreach_os.core.config import get_settings
from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import set_llm_client
from outreach_os.core.s3 import reset_for_tests
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.services.local_workspace import LOCAL_TENANT_ID
from tests.fake_llm import FakeLLMClient


@pytest.fixture(autouse=True)
def fake_llm():
    fake = FakeLLMClient()
    set_llm_client(fake)
    yield fake
    set_llm_client(None)
    reset_for_tests()


@pytest.fixture
def broker_mode(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Run as the compose stack does (no eager Celery) without a real broker:
    record any enqueue instead of sending it to Redis."""
    from outreach_os.workers.tasks import draft as draft_tasks

    monkeypatch.setattr(get_settings(), "celery_task_always_eager", False)
    enqueued: list[tuple] = []
    monkeypatch.setattr(
        draft_tasks.generate_draft, "delay", lambda *args, **kw: enqueued.append(args)
    )
    return enqueued


async def test_generate_returns_the_real_draft_when_celery_is_not_eager(
    client, broker_mode: list[tuple]
) -> None:
    resp = await client.post(
        "/v1/campaigns",
        json={
            "name": "broker-mode-camp",
            "style_sample_emails": ["Hi {first_name}, this is a test email body."],
            "steps": [{"step_number": 1, "delay_days": 0, "subject_template": "Quick question"}],
        },
    )
    assert resp.status_code == 201, resp.text
    step_id = resp.json()["steps"][0]["id"]

    from outreach_os.domain.models.lead import Lead

    async with get_session_factory()() as session, session.begin():
        await set_tenant_for_session(session, str(LOCAL_TENANT_ID))
        lead = Lead(
            tenant_id=LOCAL_TENANT_ID, source="csv_import", first_name="Dana", email="dana@example.com"
        )
        session.add(lead)
        await session.flush()
        lead_id = str(lead.id)

    resp = await client.post(
        "/v1/drafts/generate", json={"lead_id": lead_id, "step_id": step_id}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["subject"]

    fetched = await client.get(f"/v1/drafts/{body['id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == body["id"]
    assert uuid.UUID(body["id"])
