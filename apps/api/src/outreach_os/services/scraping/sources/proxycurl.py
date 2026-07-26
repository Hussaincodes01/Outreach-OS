"""LinkedIn-via-Proxycurl enrichment.

Direct LinkedIn scraping is a ToS violation. We use Proxycurl
(https://nubela.co/proxycurl/) as a data reseller. The customer
provides their own Proxycurl API key (stored as a `credential` with
kind = "proxycurl") and we call the Proxycurl REST API to look up
a person or a company.

For Phase 2, we accept a list of LinkedIn profile URLs in the ICP
(`extra["linkedin_urls"]`) and return one lead per URL. The "find
leads matching ICP" loop is out of scope for the MVP — the customer
typically uploads a seed list from Sales Navigator exports.
"""
from __future__ import annotations

import logging
from typing import Any, cast

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

PROXYCURL_PEOPLE_ENDPOINT = "https://nubela.co/proxycurl/api/v2/linkedin"


class ProxycurlError(OutreachError):
    """Raised when the Proxycurl API rejects the request or returns garbage."""


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, ProxycurlError)),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
def _fetch_profile(api_key: str, linkedin_url: str) -> dict[str, Any]:
    client = get_http()
    resp = client.get(
        PROXYCURL_PEOPLE_ENDPOINT,
        params={"url": linkedin_url, "use_cache": "if-recent"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if resp.status_code in (401, 403):
        raise ProxycurlError(f"proxycurl auth failed (status {resp.status_code})")
    if resp.status_code == 404:
        # Person not found — return empty; the orchestrating task will skip.
        return {}
    if resp.status_code == 429:
        raise ProxycurlError("proxycurl rate limit hit")
    if resp.status_code >= 500:
        raise ProxycurlError(f"proxycurl 5xx (status {resp.status_code})")
    resp.raise_for_status()
    return cast("dict[str, Any]", resp.json())


def _domain_from_company(company: dict[str, Any] | None) -> str | None:
    if not company:
        return None
    website = company.get("website") or ""
    if not website:
        return None
    from urllib.parse import urlparse

    host = urlparse(website if "://" in website else f"https://{website}").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def fetch_profile(*, api_key: str, linkedin_url: str) -> RawLead | None:
    """Fetch a single LinkedIn profile and map it to a RawLead.

    Returns None when the profile is missing or the API returns 404.
    """
    if not api_key:
        raise ProxycurlError("proxycurl api key is required")
    if not linkedin_url or "linkedin.com/in/" not in linkedin_url:
        raise ProxycurlError("a linkedin.com/in/<slug> url is required")

    try:
        data = _fetch_profile(api_key, linkedin_url)
    except httpx.HTTPError as exc:
        raise ProxycurlError(f"proxycurl network error: {exc}") from exc
    if not data:
        return None

    company = data.get("experiences", [{}])[0].get("company") if data.get("experiences") else None
    domain = _domain_from_company(company)
    full_name = data.get("full_name")
    first, _, last = (full_name or "").partition(" ")

    return RawLead(
        source="linkedin_proxycurl",
        first_name=first or None,
        last_name=last or None,
        full_name=full_name,
        domain=domain,
        company_name=company.get("name") if company else None,
        title=(data.get("experiences", [{}])[0].get("title") if data.get("experiences") else None),
        linkedin_url=linkedin_url,
        country=data.get("country_full_name") or data.get("country"),
        industry=(company or {}).get("industry"),
        company_size=(company or {}).get("company_size"),
        raw_data=data,
    )


def fetch_profiles(*, api_key: str, linkedin_urls: list[str]) -> list[RawLead]:
    """Sequentially fetch a list of profiles. We don't fan out concurrently
    because Proxycurl has per-second rate limits and the customer's plan
    dictates the right concurrency."""
    out: list[RawLead] = []
    for url in linkedin_urls:
        try:
            lead = fetch_profile(api_key=api_key, linkedin_url=url)
        except ProxycurlError as exc:
            log.warning("proxycurl lookup failed url=%s err=%s", url, exc)
            continue
        if lead is not None:
            out.append(lead)
    log.info("proxycurl returned %d/%d profiles", len(out), len(linkedin_urls))
    return out
