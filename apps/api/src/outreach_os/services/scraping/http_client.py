"""HTTP client for outbound scraping calls.

We use a single `httpx.Client` per process (sync — Scrapling and the
parsing paths are sync). The Celery worker holds one; the API process
holds one (used for "Test connection" type calls in the future).
"""
from __future__ import annotations

from threading import Lock

import httpx

from outreach_os.core.config import get_settings

_lock = Lock()
_client: httpx.Client | None = None


def get_http() -> httpx.Client:
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            settings = get_settings()
            _client = httpx.Client(
                timeout=settings.scraping_http_timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
    return _client


def reset_for_tests() -> None:
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001
                pass
            _client = None
