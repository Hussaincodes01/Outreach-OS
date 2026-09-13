"""Celery task package. Importing submodules here registers their
@celery_app.task decorators with the worker."""
from __future__ import annotations

from outreach_os.workers.tasks import (
    draft,
    inbox,
    notifications,
    scrape,
    send_tasks,
)

__all__ = ["draft", "inbox", "notifications", "scrape", "send_tasks"]
