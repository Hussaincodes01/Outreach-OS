"""Celery task wrappers for the Phase 4 send engine."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from outreach_os.core.db import run_worker_task
from outreach_os.workers.celery_app import celery_app
from outreach_os.workers.tasks.send import send_due_async

log = logging.getLogger(__name__)


@celery_app.task(name="outreach_os.workers.send_due")  # type: ignore[untyped-decorator]
def send_due(tenant_id: str | None = None) -> dict[str, Any]:
    """Celery wrapper. In eager mode this runs the async core on a
    brand-new event loop in a thread, then returns."""
    log.info("send_due start tenant=%s", tenant_id)
    started = datetime.utcnow()
    tid = uuid.UUID(tenant_id) if tenant_id else None
    summary = run_worker_task(send_due_async(tenant_id=tid))
    log.info("send_due done in %ss: %s", (datetime.utcnow() - started).total_seconds(), summary)
    return summary
