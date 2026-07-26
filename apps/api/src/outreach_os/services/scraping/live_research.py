"""Live website research — fetch a lead's homepage and extract context
for the agent draft node.

This is a lightweight module (no heavy deps like litellm/SQLAlchemy)
so it can be unit-tested without the full app stack.
"""
from __future__ import annotations

import logging

from outreach_os.core.config import get_settings
from outreach_os.services.scraping.sources.company_site import _fetch

log = logging.getLogger(__name__)


def scrape_live_context(domain: str | None) -> str:
    """Fetch the lead's homepage and return cleaned text for the draft prompt.
    Returns empty string on any failure — never raises."""
    if not domain:
        return ""
    settings = get_settings()
    if not settings.scraping_live_research_enabled:
        return ""
    try:
        from scrapling.parser import Adaptor

        status, html = _fetch(f"https://{domain}")
        if status >= 400 or not html:
            return ""
        adaptor = Adaptor(html, url=f"https://{domain}")
        parts: list[str] = []
        title = adaptor.css("title::text").get()
        if title:
            parts.append(f"Page title: {title.strip()}")
        desc = adaptor.css('meta[name="description"]::attr(content)').get()
        if desc:
            parts.append(f"Description: {desc.strip()}")
        body_text = adaptor.css("body ::text").getall()
        cleaned = " ".join(t.strip() for t in body_text if t.strip())
        if cleaned:
            words = cleaned.split()[:400]
            parts.append("Page content: " + " ".join(words))
        raw = "\n".join(parts)
        max_chars = settings.scraping_live_research_max_chars
        return raw[:max_chars] if len(raw) > max_chars else raw
    except Exception as exc:
        log.warning("live research scrape failed domain=%s err=%s", domain, exc)
        return ""
