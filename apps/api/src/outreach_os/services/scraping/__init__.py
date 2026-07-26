"""Public surface for the scraping subsystem.

The orchestrating Celery task calls `run_source(...)` with a source
name; this dispatches to the per-source module. Tests mock at this
boundary by monkey-patching `run_source`.
"""
from __future__ import annotations

import logging
from typing import Any

from outreach_os.core.errors import OutreachError
from outreach_os.services.scraping.raw_lead import RawLead
from outreach_os.services.scraping.sources import company_site, proxycurl, serper, social_profiles

log = logging.getLogger(__name__)

VALID_SOURCES = ("serper", "company_site", "linkedin_proxycurl", "social_profiles")


class SourceConfigError(OutreachError):
    """Raised when the tenant's source config is missing required fields."""


def run_source(
    source: str,
    *,
    credentials: dict[str, str],
    icp: dict[str, Any],
    config: dict[str, Any],
    limit: int,
) -> list[RawLead]:
    """Dispatch to a specific source.

    `credentials` is a dict of kind -> plaintext secret. `icp` and
    `config` are the tenant's ICP and the per-source config blob.
    """
    if source not in VALID_SOURCES:
        raise SourceConfigError(f"unknown source: {source}")

    if source == "serper":
        api_key = credentials.get("serper", "")
        if not api_key:
            raise SourceConfigError("serper credential is required for source=serper")
        query = _build_serper_query(icp)
        return serper.search(
            api_key=api_key,
            query=query,
            limit=limit,
            gl=config.get("gl", "us"),
            hl=config.get("hl", "en"),
        )

    if source == "company_site":
        domains = _domains_for_company_site(icp)
        out: list[RawLead] = []
        for domain in domains[: max(1, limit // 5)]:
            out.extend(company_site.scrape_domain(domain))
            if len(out) >= limit:
                break
        return out

    if source == "linkedin_proxycurl":
        api_key = credentials.get("proxycurl", "")
        if not api_key:
            raise SourceConfigError("proxycurl credential is required for source=linkedin_proxycurl")
        urls = icp.get("extra", {}).get("linkedin_urls", [])
        if not urls:
            log.info("proxycurl: no linkedin_urls in ICP extra; returning empty")
            return []
        return proxycurl.fetch_profiles(api_key=api_key, linkedin_urls=urls[:limit])

    if source == "social_profiles":
        urls = icp.get("extra", {}).get("social_urls", [])
        if not urls:
            log.info("social_profiles: no social_urls in ICP extra; returning empty")
            return []
        return social_profiles.scrape_profiles(urls=urls[:limit])

    raise SourceConfigError(f"unhandled source: {source}")


def _build_serper_query(icp: dict[str, Any]) -> str:
    """Compose a Google query from the ICP. Tries to be a search an
    actual human would type: 'VP Sales SaaS startups'."""
    parts: list[str] = []
    titles = icp.get("titles") or []
    if titles:
        parts.append(" OR ".join(f'"{t}"' for t in titles[:3]))
    industries = icp.get("industries") or []
    if industries:
        parts.append(" OR ".join(industries[:3]))
    geos = icp.get("geos") or []
    if geos:
        parts.append(" OR ".join(geos[:2]))
    signals = icp.get("signals") or []
    if signals:
        parts.append(" ".join(f'"{s}"' for s in signals[:2]))
    query = " ".join(p for p in parts if p).strip()
    if not query:
        query = "VP Sales"
    if icp.get("extra", {}).get("excluded_domains"):
        excluded = " ".join(f'-site:{d}' for d in icp["extra"]["excluded_domains"][:5])
        query = f"{query} {excluded}"
    return query


def _domains_for_company_site(icp: dict[str, Any]) -> list[str]:
    """For Phase 2 MVP, the company_site source expects the customer to
    hand-pick domains in `icp.extra.domains` (e.g. uploaded from a
    Sales Navigator export). Auto-discovery from Serper results is a
    Phase 3 add-on."""
    extra = icp.get("extra") or {}
    domains = extra.get("domains") or []
    return [d.strip().lower() for d in domains if d and isinstance(d, str)]
