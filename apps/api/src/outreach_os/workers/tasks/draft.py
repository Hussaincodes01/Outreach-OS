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

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.services.draft_service import DraftService
from outreach_os.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def generate_draft_async(
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    lead_id: uuid.UUID,
    step_id: uuid.UUID,
    force_regenerate: bool = False,
):
    """Pure-async core: no Celery dependency. Returns the
    DraftGenerationResult from the DraftService."""
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tenant_id))
        service = DraftService(session)
        result = await service.generate_draft(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            lead_id=lead_id,
            step_id=step_id,
            force_regenerate=force_regenerate,
        )
    return result


@celery_app.task(name="outreach_os.workers.generate_draft")
def generate_draft(
    tenant_id: str,
    campaign_id: str,
    lead_id: str,
    step_id: str,
    force_regenerate: bool = False,
) -> dict[str, Any]:
    """Celery wrapper. In eager mode this runs the async core on a fresh
    event loop in a thread, then returns. In production this is a no-op
    that dispatches to a real worker."""
    from outreach_os.core.config import get_settings

    started = datetime.utcnow()
    settings = get_settings()
    log.info(
        "generate_draft start tenant=%s campaign=%s lead=%s step=%s",
        tenant_id, campaign_id, lead_id, step_id,
    )
    if settings.celery_task_always_eager:
        # Tests run the async core inline.
        summary = asyncio.run(
            generate_draft_async(
                tenant_id=uuid.UUID(tenant_id),
                campaign_id=uuid.UUID(campaign_id),
                lead_id=uuid.UUID(lead_id),
                step_id=uuid.UUID(step_id),
                force_regenerate=force_regenerate,
            )
        )
    else:
        # Production: a separate worker process consumes the queue and
        # runs `generate_draft_async` there. The calling thread MUST NOT
        # block on the async core, so we return immediately.
        log.info(
            "generate_draft dispatched tenant=%s campaign=%s lead=%s step=%s",
            tenant_id, campaign_id, lead_id, step_id,
        )
        return {"status": "dispatched"}
    log.info(
        "generate_draft done tenant=%s draft=%s status=%s elapsed=%.2fs",
        tenant_id,
        summary.get("draft_id"),
        summary.get("status"),
        (datetime.utcnow() - started).total_seconds(),
    )
    return summary
