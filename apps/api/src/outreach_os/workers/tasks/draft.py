"""Phase 3 — async draft-generation tasks.

- `generate_draft_async(...)` — pure async core, no Celery. Used by the
  test suite (and could be used by any in-process scheduler).
- `generate_draft(...)` — Celery wrapper. In production it dispatches to a
  worker via the broker. With `task_always_eager=True` (tests) it calls
  the async core in a thread and returns the result.

The async core opens a fresh DB session, sets the RLS GUC, runs the
`DraftService.generate_draft` pipeline (which writes the AgentRun + Draft
rows and uploads the body to S3), and commits.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from outreach_os.core.db import run_worker_task, session_scope
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.services.draft_service import DraftGenerationResult, DraftService
from outreach_os.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def generate_draft_async(
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    lead_id: uuid.UUID,
    step_id: uuid.UUID,
    force_regenerate: bool = False,
) -> DraftGenerationResult:
    """Pure-async core: no Celery dependency. Returns the
    DraftGenerationResult from the DraftService."""
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tenant_id))
        service = DraftService(session)
        return await service.generate_draft(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            step_id=step_id,
            force_regenerate=force_regenerate,
        )


@celery_app.task(name="outreach_os.workers.generate_draft")  # type: ignore[untyped-decorator]
def generate_draft(
    tenant_id: str,
    campaign_id: str,
    lead_id: str,
    step_id: str,
    force_regenerate: bool = False,
) -> dict[str, Any]:
    """Celery task body — always runs the pipeline.

    This function IS the work. Whether it executes in a worker process or
    inline is Celery's decision (`task_always_eager`); either way the body
    must run, so it must not branch on that setting. The API no longer
    enqueues it (`DraftService.dispatch_generate_draft` runs in-process); it
    stays registered so messages already on the broker still execute.
    """
    started = datetime.utcnow()
    log.info(
        "generate_draft start tenant=%s campaign=%s lead=%s step=%s",
        tenant_id, campaign_id, lead_id, step_id,
    )
    summary = run_worker_task(
        generate_draft_async(
            tenant_id=uuid.UUID(tenant_id),
            campaign_id=uuid.UUID(campaign_id),
            lead_id=uuid.UUID(lead_id),
            step_id=uuid.UUID(step_id),
            force_regenerate=force_regenerate,
        )
    )
    log.info(
        "generate_draft done tenant=%s draft=%s status=%s elapsed=%.2fs",
        tenant_id,
        summary.draft_id,
        summary.status,
        (datetime.utcnow() - started).total_seconds(),
    )
    return {
        "draft_id": str(summary.draft_id),
        "agent_run_id": str(summary.agent_run_id),
        "status": summary.status,
        "subject": summary.subject,
        "model_used": summary.model_used,
        "error": summary.error,
    }
