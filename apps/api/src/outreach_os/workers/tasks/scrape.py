"""Phase 2 — async scraping tasks.

Two pieces:
- `run_scraping_job_async(job_id, tenant_id)` — pure async core, no
  Celery. Used by the test suite (and could be used by any in-process
  scheduler).
- `run_scraping_job` — Celery wrapper. In production it dispatches to a
  worker via the broker. With `task_always_eager=True` (tests) it runs
  the async core on a fresh event loop in a thread, then returns.

The orchestrating flow: open a session, set the RLS GUC, then loop
over the job's requested sources, calling the scraping service for
each, and inserting the deduped leads. Updates the job's `status`,
`found_count`, `started_at`, `completed_at` along the way.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from outreach_os.core.db import session_scope
from outreach_os.core.rate_limit import check_and_consume
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.lead_source import LeadSource
from outreach_os.domain.models.scraping_job import ScrapingJob, ScrapingJobStatus
from outreach_os.services import lead_service, scraping
from outreach_os.services.credential_lookup import get_credential_secrets
from outreach_os.workers.celery_app import celery_app

log = logging.getLogger(__name__)


async def run_scraping_job_async(job_id: uuid.UUID, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Pure-async core: no Celery dependency. Returns a small summary
    dict the caller can log or surface to a dashboard."""
    from outreach_os.domain.models.icp import Icp

    started_at_wall = datetime.utcnow()
    summary: dict[str, Any] = {"job_id": str(job_id), "sources": {}}

    async with session_scope() as session:
        await set_tenant_for_session(session, str(tenant_id))
        job = await session.get(ScrapingJob, job_id)
        if job is None:
            raise ValueError(f"scraping job {job_id} not found for tenant {tenant_id}")
        if job.status not in {ScrapingJobStatus.PENDING.value, ScrapingJobStatus.RUNNING.value}:
            log.info("scrape job %s already in terminal state %s; skipping", job_id, job.status)
            return summary
        icp = await session.get(Icp, job.icp_id)
        if icp is None:
            raise ValueError(f"icp {job.icp_id} missing for job {job_id}")

        job.status = ScrapingJobStatus.RUNNING.value
        job.started_at = started_at_wall
        await session.flush()

        source_rows = (
            await session.execute(
                select(LeadSource).where(LeadSource.tenant_id == tenant_id)
            )
        ).scalars().all()
        source_config = {r.source: r for r in source_rows}

        secrets = await get_credential_secrets(
            session,
            tenant_id=tenant_id,
            kinds=["serper", "proxycurl"],
        )

        icp_dict = {
            "name": icp.name,
            "description": icp.description,
            "industries": list(icp.industries or []),
            "company_sizes": list(icp.company_sizes or []),
            "geos": list(icp.geos or []),
            "titles": list(icp.titles or []),
            "signals": list(icp.signals or []),
            "extra": dict(icp.extra or {}),
        }

        total_inserted = 0
        total_duplicates = 0
        for source in job.sources:
            src = source_config.get(source)
            if src is None or not src.is_enabled:
                summary["sources"][source] = {"skipped": "not enabled"}
                continue
            decision = check_and_consume(str(tenant_id), source)
            if not decision.allowed:
                summary["sources"][source] = {
                    "skipped": "rate-limited",
                    "retry_after": decision.retry_after_seconds,
                }
                continue
            try:
                raw = scraping.run_source(
                    source,
                    credentials=secrets,
                    icp=icp_dict,
                    config=dict(src.config or {}),
                    limit=job.requested_count,
                )
            except Exception as exc:
                log.exception("scrape source %s failed", source)
                summary["sources"][source] = {"error": str(exc)[:200]}
                continue
            inserted, duplicates = await lead_service.insert_leads(
                session,
                tenant_id=tenant_id,
                job_id=job_id,
                raw_leads=raw,
            )
            log.info("scrape source=%s raw=%d inserted=%d duplicates=%d", source, len(raw), inserted, duplicates)
            total_inserted += inserted
            total_duplicates += duplicates
            if src is not None:
                src.last_run_at = datetime.utcnow()
            summary["sources"][source] = {
                "raw_count": len(raw),
                "inserted": inserted,
                "duplicates": duplicates,
            }

        job.found_count = total_inserted
        job.status = ScrapingJobStatus.COMPLETED.value
        job.completed_at = datetime.utcnow()
        await session.flush()
        summary["total_inserted"] = total_inserted
        summary["total_duplicates"] = total_duplicates

        # Phase 7: record lead usage.
        try:
            from outreach_os.services.billing_service import record_usage

            if total_inserted > 0:
                await record_usage(
                    session,
                    tenant_id=tenant_id,
                    metric="lead_scraped",
                    quantity=total_inserted,
                    source="scraping_job",
                    source_id=job.id,
                )
        except Exception:
            log.exception("record_usage(lead_scraped) failed")

        try:
            from outreach_os.services.notification_service import publish

            await publish(
                session,
                tenant_id=tenant_id,
                event_key="scraping.completed",
                severity="success",
                title=f"Scraping complete: {total_inserted} leads",
                target_type="scraping_job",
                target_id=job.id,
                payload={
                    "total_inserted": total_inserted,
                    "total_duplicates": total_duplicates,
                },
            )
        except Exception:
            log.exception("notification dispatch failed for scraping.completed")

        return summary


@celery_app.task(name="outreach_os.scrape.run_job", max_retries=2)  # type: ignore[untyped-decorator]
def run_scraping_job(job_id: str, tenant_id: str) -> dict[str, Any]:
    """Celery entrypoint. In production this runs in a worker process.
    With `task_always_eager=True` (test mode) we run the async core on
    a fresh event loop in a worker thread so the SQLAlchemy async engine
    can initialise correctly."""
    job_uuid = uuid.UUID(job_id)
    tenant_uuid = uuid.UUID(tenant_id)

    # We do NOT call run_scraping_job_async directly from the event loop
    # (the test's loop) because `asyncio.run` cannot nest. Instead we
    # run it in a thread with its own loop. SQLAlchemy's async engine
    # holds connections per loop, so this is the safe pattern.
    result_box: list[Any] = []
    error_box: list[BaseException] = []

    def _runner() -> None:
        try:
            result_box.append(asyncio.run(run_scraping_job_async(job_uuid, tenant_uuid)))
        except BaseException as exc:
            error_box.append(exc)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()

    if error_box:
        exc = error_box[0]
        log.exception("scrape job %s failed", job_id)
        # Best-effort mark as failed.
        def _mark_failed() -> None:
            try:
                asyncio.run(_mark_job_failed_async(job_uuid, tenant_uuid, str(exc)[:500]))
            except Exception:
                log.exception("failed to mark job %s as failed", job_id)
        _mark_failed()
        raise exc
    return result_box[0] if result_box else {}


async def _mark_job_failed_async(job_id: uuid.UUID, tenant_id: uuid.UUID, error: str) -> None:
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tenant_id))
        job = await session.get(ScrapingJob, job_id)
        if job is not None:
            job.status = ScrapingJobStatus.FAILED.value
            job.error = error
            job.completed_at = datetime.utcnow()
            try:
                from outreach_os.services.notification_service import publish

                await publish(
                    session,
                    tenant_id=tenant_id,
                    event_key="scraping.failed",
                    severity="error",
                    title="Scraping job failed",
                    body=error[:280],
                    target_type="scraping_job",
                    target_id=job_id,
                    payload={"found_count": job.found_count or 0},
                )
            except Exception:
                log.exception("notification dispatch failed for scraping.failed")
