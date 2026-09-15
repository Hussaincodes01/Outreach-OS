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
    # Default time limits for every task, so a hung network call can't hold a
    # worker slot forever. The soft limit raises SoftTimeLimitExceeded inside
    # the task; the hard limit kills the worker child.
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    # Phase 6 beat schedule.
    beat_schedule={
        "outreach_os.notifications.send_email_digest": {
            "task": "outreach_os.notifications.send_email_digest",
            "schedule": float(settings.notification_email_digest_interval_seconds),
        },
        # Fires due SequenceStep rows through the mailbox's own SMTP. Without
        # this entry `send_due` exists but nothing ever calls it. `expires`
        # drops a queued run the worker didn't start before the next one is
        # due, so a backlog never replays as a burst.
        "outreach_os.workers.send_due": {
            "task": "outreach_os.workers.send_due",
            "schedule": float(settings.send_due_interval_seconds),
            "options": {"expires": float(settings.send_due_interval_seconds)},
        },
        # Captures replies for mailboxes that only offer IMAP (no inbound
        # webhook). Without this entry `poll_inboxes` exists but nothing
        # ever calls it.
        "outreach_os.workers.poll_inboxes": {
            "task": "outreach_os.workers.poll_inboxes",
            "schedule": float(settings.inbox_poll_interval_seconds),
            "options": {"expires": float(settings.inbox_poll_interval_seconds)},
        },
    },
)

# Import the task package so @celery_app.task decorators run and the
# worker can find them by name.
import outreach_os.workers.tasks  # noqa: E402, F401
