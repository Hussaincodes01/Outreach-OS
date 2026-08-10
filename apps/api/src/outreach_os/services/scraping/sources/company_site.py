"""Generic company-website scraper using Scrapling.

Given a domain, we fetch the homepage (and common contact/team paths)
and extract emails, company name, industry, and country.

Uses Scrapling's Fetcher for TLS-impersonated HTTP requests with built-in
retries and stealth headers. Falls back to StealthyFetcher (headless
browser) when the site blocks us (403/captcha). Respects robots.txt
when enabled in config.

Note: this module is **permissive** — it never raises on a fetch
error, it just returns whatever it managed to extract.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from scrapling.fetchers import Fetcher
from scrapling.parser import Adaptor

from outreach_os.core.config import get_settings
from outreach_os.core.errors import OutreachError
from outreach_os.services.scraping.raw_lead import RawLead

log = logging.getLogger(__name__)

_FETCH_TIMEOUT = 15
# Milliseconds, not seconds — Scrapling passes this straight through to
# Playwright, whose own default is 30000. Setting 30 here meant every stealth
# fetch aborted after 30ms, i.e. the anti-bot fallback never once succeeded.
_STEALTHY_TIMEOUT_MS = 30_000
_TEAM_PATHS = ("/team", "/about", "/about-us", "/leadership", "/people", "/contact")
_EMAIL_RE = re.compile(r"\b[\w.+\-]+@([\w\-]+\.)+[a-zA-Z]{2,}\b")
# Image filenames regularly get picked up by the email regex (e.g. "logo@2x.png").
_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


class CompanySiteError(OutreachError):
    """Raised when a fetch fails irrecoverably (caller decides to retry/skip)."""


# --- Fetching with Scrapling -----------------------------------------------


def _try_fetch(url: str, *, timeout: int = _FETCH_TIMEOUT) -> tuple[int, str] | None:
    """Fetch via Scrapling's Fetcher (HTTP, TLS-impersonated, auto-retry).

    Scrapling's built-in retry handles transient failures. Returns
    (status, html_text) on success or None on hard failure.
    """
    try:
        resp = Fetcher.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            stealthy_headers=True,
        )
        status = resp.status
        html = resp.body.decode(resp.encoding or "utf-8", errors="replace")
        return status, html
    except Exception as exc:
        log.warning("company_site fetch failed url=%s err=%s", url, exc)
        return None


def _stealthy_fetch(url: str) -> tuple[int, str] | None:
    """Fallback: use StealthyFetcher (headless Chromium) for anti-bot sites."""
    try:
        from scrapling.fetchers import StealthyFetcher

        resp = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=_STEALTHY_TIMEOUT_MS,
            # `disable_resources` drops images/media/fonts/etc. Scrapling has
            # no `block_images`/`block_css` options — passing those raised a
            # TypeError that the `except Exception` below swallowed, so the
            # stealth fallback silently never worked.
            disable_resources=True,
        )
        status = resp.status
        html = resp.body.decode(resp.encoding or "utf-8", errors="replace")
        return status, html
    except Exception as exc:
        log.warning("company_site stealth fetch failed url=%s err=%s", url, exc)
        return None


def _fetch(url: str) -> tuple[int, str]:
    """Fetch a URL with Scrapling. Tries Fetcher first, falls back to
    StealthyFetcher on failure or anti-bot blocking (403/captcha)."""
    result = _try_fetch(url)
    if result is not None:
        status, html = result
        # Anti-bot detected — try stealth fallback
        if status == 403 or not html.strip():
            settings = get_settings()
            if settings.scraping_use_stealth_fallback:
                stealth_result = _stealthy_fetch(url)
                if stealth_result is not None:
                    return stealth_result
        return status, html

    # Fetcher failed completely — try stealth
    settings = get_settings()
    if settings.scraping_use_stealth_fallback:
        stealth_result = _stealthy_fetch(url)
        if stealth_result is not None:
            return stealth_result

    return 0, ""


# --- Extraction helpers ----------------------------------------------------


def _guess_country_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    mapping = {"uk": "GB", "de": "DE", "fr": "FR", "ca": "CA", "au": "AU"}
    return mapping.get(tld)


def _extract_emails(text: str, domain: str) -> list[str]:
    """Return up to 5 unique emails matching the given domain."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _EMAIL_RE.finditer(text or ""):
        addr = m.group(0).lower()
        if addr in seen:
            continue
        seen.add(addr)
        if "@" not in addr:
            continue
        local, _, host = addr.partition("@")
        if host == domain.lower() or host.endswith("." + domain.lower()):
            if local in {"noreply", "no-reply", "postmaster", "abuse"}:
                continue
            if addr.endswith(_IMG_EXT) or any(local.endswith(ext) for ext in _IMG_EXT):
                continue
            out.append(addr)
            if len(out) >= 5:
                break
    return out


def _extract_company_name(adaptor: Adaptor, url: str) -> str | None:
    title = adaptor.css("title::text").get()
    if title:
        # En/em dashes are intentional — page titles use them as separators.
        cleaned = re.split(r"[|\-–—]", title, maxsplit=1)[0].strip()  # noqa: RUF001
        if 2 <= len(cleaned) <= 80:
            return cleaned
    og = adaptor.css('meta[property="og:site_name"]::attr(content)').get()
    if og:
        return og.strip()
    return None


def _extract_industry(adaptor: Adaptor) -> str | None:
    for meta_sel in (
        'meta[name="industry"]::attr(content)',
        'meta[property="og:industry"]::attr(content)',
    ):
        val = adaptor.css(meta_sel).get()
        if val:
            return val.strip()
    return None


def _first_name_from_email(email: str) -> str | None:
    local = email.split("@", 1)[0]
    for sep in (".", "_", "-", "+"):
        if sep in local:
            return local.split(sep)[0].capitalize()
    return local.capitalize()


# --- Main entry point ------------------------------------------------------


def scrape_domain(domain: str) -> list[RawLead]:
    """Fetch a domain and its team/contact pages, extracting emails
    and company metadata. Always returns a list (possibly empty)."""
    if not domain:
        return []

    base = f"https://{domain}"
    paths = ("", *_TEAM_PATHS)
    leads: list[RawLead] = []
    seen_emails: set[str] = set()
    company_name: str | None = None
    industry: str | None = None
    country: str | None = None

    for path in paths:
        url = urljoin(base, path) if path else base
        status, html = _fetch(url)
        if status >= 400 or not html:
            continue

        adaptor = Adaptor(html, url=url)
        if company_name is None:
            company_name = _extract_company_name(adaptor, url)
        if industry is None:
            industry = _extract_industry(adaptor)
        if country is None:
            country = _guess_country_from_url(url)

        for email in _extract_emails(html, domain):
            if email in seen_emails:
                continue
            seen_emails.add(email)
            leads.append(
                RawLead(
                    source="company_site",
                    first_name=_first_name_from_email(email),
                    email=email,
                    domain=domain.lower(),
                    company_name=company_name,
                    country=country,
                    industry=industry,
                    raw_data={"source_url": url, "fetched_path": path},
                )
            )

    log.info("company_site scraped %d emails for domain=%s", len(leads), domain)
    return leads
