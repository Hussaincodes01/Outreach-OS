"""Phase 4 send Celery task.

`send_due_async(tenant_id=None)` processes all due SequenceStep rows
for the given tenant (or all active tenants) and fires the next email.
Returns a dict summary of what happened.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.tenant import Tenant
from outreach_os.services.send_service import SendService

log = logging.getLogger(__name__)


async def _list_active_tenant_ids() -> list[uuid.UUID]:
    async with session_scope() as session:
        rows = await session.execute(
            select(Tenant.id).where(Tenant.status == "active")
        )
        return [r[0] for r in rows.all()]


async def send_due_async(tenant_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Run a single pass of the send engine.

    If `tenant_id` is given, only that tenant's steps are processed.
    Otherwise, every active tenant is processed.
    """
    if tenant_id is None:
        tenants = await _list_active_tenant_ids()
    else:
        tenants = [tenant_id]
    sent_total = 0
    failed_total = 0
    skipped_total = 0
    for tid in tenants:
        async with session_scope() as session:
            await set_tenant_for_session(session, str(tid))
            svc = SendService(session)
            sends = await svc.execute_due(tenant_id=tid)
            for s in sends:
                if s.status == "sent":
                    sent_total += 1
                elif s.status == "failed":
                    failed_total += 1
                else:
                    skipped_total += 1
    return {
        "tenants": len(tenants),
        "sent": sent_total,
        "failed": failed_total,
        "skipped": skipped_total,
    }
