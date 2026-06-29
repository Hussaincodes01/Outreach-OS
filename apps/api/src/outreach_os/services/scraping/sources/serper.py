"""Serper.dev search-scraping source.

Serper is a Google Search API. We POST a search query and get back
organic results with `title`, `link`, `snippet`, and (sometimes)
extracted attributes. The "leads" here are companies + the snippets
that mention a person; we then try to enrich a contact email from
the company website in a second pass (handled by the orchestrating
Celery task, not this module).

API: https://google.serper.dev/search
Auth: `X-API-KEY: $SERPER_API_KEY` header. Sign up at serper.dev for
a free key (2,500 queries). The key is read from the per-tenant
`credential` table (kind = "serper") so each customer brings their
own key.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from outreach_os.core.errors import OutreachError
from outreach_os.services.scraping.http_client import get_http
from outreach_os.services.scraping.raw_lead import RawLead

log = logging.getLogger(__name__)

SERPER_ENDPOINT = "https://google.serper.dev/search"


class SerperError(OutreachError):
    """Raised when the Serper API rejects the request or returns garbage."""


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, SerperError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
def _post_serper(api_key: str, query: str, gl: str, hl: str, num: int) -> dict[str, Any]:
    client = get_http()
    resp = client.post(
        SERPER_ENDPOINT,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "gl": gl, "hl": hl, "num": min(num, 100)},
    )
    if resp.status_code == 401 or resp.status_code == 403:
        raise SerperError(f"serper auth failed (status {resp.status_code})")
    if resp.status_code >= 500:
        raise SerperError(f"serper 5xx (status {resp.status_code})")
    resp.raise_for_status()
    return resp.json()


def _domain_from_url(url: str) -> str | None:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:  # noqa: BLE001
        return None


def _split_title(title: str) -> tuple[str | None, str | None]:
    """Best-effort: 'Jane Doe - VP Sales, Acme' -> (Jane Doe, VP Sales, Acme)."""
    if not title:
        return None, None
    parts = [p.strip() for p in title.split(" - ", 1)]
    if len(parts) == 2:
        return parts[0], parts[1]
    if " | " in title:
        return title.split(" | ", 1)[0].strip(), None
    return title.strip(), None


def search(
    *,
    api_key: str,
    query: str,
    limit: int = 50,
    gl: str = "us",
    hl: str = "en",
) -> list[RawLead]:
    """Run a Serper search and return parsed leads.

    The Serper response has `organic[*]` with title/link/snippet. We
    treat each result as a "company" lead; the snippet often contains
    a person's name which we surface as `full_name`. We do NOT make
    up emails here — the company_site pass is the one that
    discovers them.
    """
    if not api_key:
        raise SerperError("serper api key is required")
    if not query.strip():
        raise SerperError("query is required")

    try:
        data = _post_serper(api_key, query, gl=gl, hl=hl, num=limit)
    except httpx.HTTPError as exc:
        raise SerperError(f"serper network error: {exc}") from exc

    leads: list[RawLead] = []
    for item in data.get("organic", []) or []:
        link = item.get("link") or ""
        title = item.get("title") or ""
        snippet = item.get("snippet") or ""
        domain = _domain_from_url(link)
        if not domain:
            continue
        person_name, inferred_title = _split_title(title)
        leads.append(
            RawLead(
                source="serper",
                full_name=person_name,
                title=inferred_title,
                domain=domain,
                company_name=domain.split(".")[0].capitalize(),
                raw_data={"link": link, "title": title, "snippet": snippet},
            )
        )
    log.info("serper returned %d organic results for query=%r", len(leads), query)
    return leads
