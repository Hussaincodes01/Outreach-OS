"""Social-profiles scraping source.

Scrapes public social media profiles (Twitter/X, GitHub) using Scrapling
to extract name, bio, location, and profile URLs. No API keys needed —
uses direct HTTP fetching with TLS impersonation.

For LinkedIn, the customer should use the `linkedin_proxycurl` source
(LinkedIn actively blocks scrapers). This source handles the "long tail"
of other platforms where public profiles are accessible.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from scrapling.fetchers import Fetcher

from outreach_os.core.errors import OutreachError
from outreach_os.services.scraping.raw_lead import RawLead

log = logging.getLogger(__name__)

_FETCH_TIMEOUT = 15


class SocialProfilesError(OutreachError):
    """Raised when a profile fetch fails irrecoverably."""


def _safe_fetch(url: str) -> tuple[int, str] | None:
    """Fetch via Scrapling's Fetcher. Returns (status, html) or None."""
    try:
        resp = Fetcher.get(
            url,
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            stealthy_headers=True,
        )
        html = resp.body.decode(resp.encoding or "utf-8", errors="replace")
        return resp.status, html
    except Exception as exc:
        log.warning("social_profiles fetch failed url=%s err=%s", url, exc)
        return None


def _extract_twitter_profile(url: str, html: str) -> RawLead | None:
    """Extract Twitter/X profile data from the page HTML."""
    try:
        from scrapling.parser import Adaptor

        adaptor = Adaptor(html, url=url)
        # Twitter embeds structured data in meta tags
        name = (
            adaptor.css('meta[property="og:title"]::attr(content)').get()
            or adaptor.css('meta[name="twitter:title"]::attr(content)').get()
            or ""
        )
        bio = (
            adaptor.css('meta[property="og:description"]::attr(content)').get()
            or adaptor.css('meta[name="twitter:description"]::attr(content)').get()
            or ""
        )
        # Extract username from URL
        path = urlparse(url).path.rstrip("/")
        username = path.split("/")[-1] if path else ""
        if not name and not username:
            return None
        # Clean name: "John Doe (@johndoe) on X" -> "John Doe"
        name = re.sub(r"\s*\(.*$", "", name).strip()
        if not name:
            name = username
        first, _, last = name.partition(" ")
        return RawLead(
            source="social_profiles",
            first_name=first or None,
            last_name=last or None,
            full_name=name,
            raw_data={
                "platform": "twitter",
                "url": url,
                "username": username,
                "bio": bio[:500],
            },
        )
    except Exception as exc:
        log.warning("twitter parse failed url=%s err=%s", url, exc)
        return None


def _extract_github_profile(url: str, html: str) -> RawLead | None:
    """Extract GitHub profile data from the page HTML."""
    try:
        from scrapling.parser import Adaptor

        adaptor = Adaptor(html, url=url)
        name = adaptor.css('meta[property="og:title"]::attr(content)').get() or ""
        bio = (
            adaptor.css('meta[property="og:description"]::attr(content)').get()
            or adaptor.css('meta[name="description"]::attr(content)').get()
            or ""
        )
        # Extract username from URL
        path = urlparse(url).path.rstrip("/")
        username = path.split("/")[-1] if path else ""
        if not name and not username:
            return None
        name = name.strip() or username
        first, _, last = name.partition(" ")
        return RawLead(
            source="social_profiles",
            first_name=first or None,
            last_name=last or None,
            full_name=name,
            raw_data={
                "platform": "github",
                "url": url,
                "username": username,
                "bio": bio[:500],
            },
        )
    except Exception as exc:
        log.warning("github parse failed url=%s err=%s", url, exc)
        return None


def _detect_platform(url: str) -> str:
    """Detect social platform from URL domain."""
    host = urlparse(url).netloc.lower()
    if "twitter.com" in host or "x.com" in host:
        return "twitter"
    if "github.com" in host:
        return "github"
    return "unknown"


def scrape_profiles(urls: list[str]) -> list[RawLead]:
    """Scrape a list of social profile URLs and return parsed leads.

    Each URL is fetched with Scrapling's TLS-impersonated HTTP client.
    Supported platforms: Twitter/X, GitHub.
    """
    out: list[RawLead] = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        platform = _detect_platform(url)
        if platform == "unknown":
            log.info("social_profiles: skipping unsupported platform url=%s", url)
            continue
        result = _safe_fetch(url)
        if result is None:
            continue
        status, html = result
        if status >= 400 or not html:
            continue
        if platform == "twitter":
            lead = _extract_twitter_profile(url, html)
        elif platform == "github":
            lead = _extract_github_profile(url, html)
        else:
            continue
        if lead is not None:
            out.append(lead)
    log.info("social_profiles scraped %d/%d urls", len(out), len(urls))
    return out
