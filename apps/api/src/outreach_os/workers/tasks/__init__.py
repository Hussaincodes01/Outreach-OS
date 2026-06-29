"""Celery task package. Importing submodules here registers their
@celery_app.task decorators with the worker."""
from __future__ import annotations

from outreach_os.workers.tasks import (
    draft,
    notifications,
    scrape,
    send_tasks,
)  # noqa: F401

__all__ = ["draft", "notifications", "scrape", "send_tasks"]
