"""Celery application factory.

Tasks are registered via the `outreach_os.workers.tasks` package import
below (autodiscovery).
"""
from __future__ import annotations

from celery import Celery

from outreach_os.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "outreach_os",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    # Phase 6 beat schedule.
    beat_schedule={
        "outreach_os.notifications.send_email_digest": {
            "task": "outreach_os.notifications.send_email_digest",
            "schedule": float(settings.notification_email_digest_interval_seconds),
        },
    },
)

# Import the task package so @celery_app.task decorators run and the
# worker can find them by name.
import outreach_os.workers.tasks  # noqa: E402, F401
