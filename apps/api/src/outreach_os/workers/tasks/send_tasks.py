"""Celery task wrappers for the Phase 4 send engine."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from outreach_os.workers.celery_app import celery_app
from outreach_os.workers.tasks.send import send_due_async

log = logging.getLogger(__name__)


@celery_app.task(name="outreach_os.workers.send_due")
def send_due(tenant_id: str | None = None) -> dict:
    """Celery wrapper. In eager mode this runs the async core on a
    brand-new event loop in a thread, then returns."""
    log.info("send_due start tenant=%s", tenant_id)
    started = datetime.utcnow()
    tid = uuid.UUID(tenant_id) if tenant_id else None
    summary = asyncio.run(send_due_async(tenant_id=tid))
    log.info("send_due done in %ss: %s", (datetime.utcnow() - started).total_seconds(), summary)
    return summary
