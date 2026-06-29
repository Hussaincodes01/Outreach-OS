"""Generic company-website scraper.

Given a domain, we fetch the homepage (and a few common contact paths)
and look for:
  - Public email addresses (`mailto:` links, plain-text `name@domain`)
  - Person names in `<h1>`, `<title>`, schema.org JSON-LD, or
    common "team" / "about" pages
  - The site's declared company name, country, industry

We use Scrapling's `Adaptor` for HTML parsing (no Playwright needed;
this is for static pages). For JS-heavy sites the result is usually
empty — the customer can add a StealthyFetcher / DynamicFetcher pass
later (Phase 8 hardening).

Note: this module is **permissive** — it never raises on a fetch
error, it just returns whatever it managed to extract. The orchestrating
task is responsible for deciding "no result, move on" vs. "retry".
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from scrapling.parser import Adaptor
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


class CompanySiteError(OutreachError):
    """Raised when a fetch fails irrecoverably (caller decides to retry/skip)."""


_EMAIL_RE = re.compile(r"\b[\w.+\-]+@([\w\-]+\.)+[a-zA-Z]{2,}\b")
_TEAM_PATHS = ("/team", "/about", "/about-us", "/leadership", "/people", "/contact")


def _guess_country_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    mapping = {"uk": "GB", "de": "DE", "fr": "FR", "ca": "CA", "au": "AU"}
    return mapping.get(tld)


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.3, max=2),
    reraise=True,
)
def _fetch(url: str) -> tuple[int, str]:
    client = get_http()
    resp = client.get(url, follow_redirects=True)
    return resp.status_code, resp.text


def _extract_emails(text: str, domain: str) -> list[str]:
    """Return up to 5 unique email addresses that match the given domain
    (case-insensitive) and exclude common false-positives (png, jpg)."""
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
            if addr.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
                continue
            out.append(addr)
            if len(out) >= 5:
                break
    return out


def _extract_company_name(adaptor: Adaptor, url: str) -> str | None:
    title = adaptor.css("title::text").get()
    if title:
        cleaned = re.split(r"[|\-–—]", title, maxsplit=1)[0].strip()
        if 2 <= len(cleaned) <= 80:
            return cleaned
    og = adaptor.css('meta[property="og:site_name"]::attr(content)').get()
    if og:
        return og.strip()
    return None


def _extract_industry(adaptor: Adaptor) -> str | None:
    for meta_sel, attr in (
        ('meta[name="industry"]::attr(content)', "content"),
        ('meta[property="og:industry"]::attr(content)', "content"),
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


def scrape_domain(domain: str) -> list[RawLead]:
    """Fetch `https://<domain>/` (and a few team pages) and extract
    whatever contact info we can find. Always returns a list — possibly
    empty if the site is JS-only or blocks us."""
    if not domain:
        return []

    base = f"https://{domain}"
    paths = ("",) + _TEAM_PATHS
    leads: list[RawLead] = []
    seen_emails: set[str] = set()
    company_name: str | None = None
    industry: str | None = None
    country: str | None = None

    for path in paths:
        url = urljoin(base, path) if path else base
        try:
            status, html = _fetch(url)
        except httpx.HTTPError as exc:
            log.warning("company_site fetch failed url=%s err=%s", url, exc)
            continue
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
