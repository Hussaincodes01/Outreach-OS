"""Slack incoming-webhook client.

The Protocol is small on purpose \u2014 we only need to deliver a single
JSON payload to a URL. Real implementation uses httpx; tests use the
in-memory stub.

`sync_send` is the only required method. We don't add retries here \u2014
that's the worker's job (so the HTTP call doesn't block the API request
that triggered the notification).
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


class SlackClient(Protocol):
    def sync_send(self, *, webhook_url: str, payload: dict[str, Any]) -> bool: ...


class HttpSlackClient:
    """httpx-based implementation. Used in dev/prod."""

    def __init__(self, *, timeout: float = 5.0) -> None:
        self._timeout = timeout

    def sync_send(self, *, webhook_url: str, payload: dict[str, Any]) -> bool:
        try:
            resp = httpx.post(webhook_url, json=payload, timeout=self._timeout)
        except httpx.HTTPError as e:
            logger.warning("slack: transport error: %s", e)
            return False
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("slack: non-2xx response: %s body=%s", resp.status_code, resp.text[:200])
        return False


class StubSlackClient:
    """In-memory Slack client for tests.

    Records every `sync_send` call in `self.calls: list[dict]` and
    supports a `next_status` knob so tests can simulate non-2xx and
    transport failures.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.next_status: int | None = 200
        self.raise_on_next: Exception | None = None

    def sync_send(self, *, webhook_url: str, payload: dict[str, Any]) -> bool:
        self.calls.append({"webhook_url": webhook_url, "payload": payload})
        if self.raise_on_next is not None:
            exc = self.raise_on_next
            self.raise_on_next = None
            raise exc
        if self.next_status is None:
            return False
        return 200 <= self.next_status < 300

    def reset(self) -> None:
        self.calls.clear()
        self.next_status = 200
        self.raise_on_next = None


_client: SlackClient | None = None


def get_slack_client() -> SlackClient:
    global _client
    if _client is None:
        _client = HttpSlackClient()
    return _client


def set_slack_client(client: SlackClient) -> None:
    """Test seam \u2014 swap the global client for a stub."""
    global _client
    _client = client


__all__ = [
    "HttpSlackClient",
    "SlackClient",
    "StubSlackClient",
    "get_slack_client",
    "set_slack_client",
]
