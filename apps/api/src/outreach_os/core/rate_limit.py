"""Rate limiter backed by Redis (fixed-window counter).

Provides:
- Per-tenant, per-source limits for scraping (serper, company_site, linkedin_proxycurl)
- Global IP-based limits for auth endpoints (login, signup, refresh)
- Global IP-based limits for webhooks

Returns a `RateLimitDecision` with `allowed`, `current`, `limit`, `retry_after_seconds`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from outreach_os.core.config import get_settings
from outreach_os.core.redis_client import get_redis

SCRAPE_DEFAULTS: Final[dict[str, int]] = {
    "serper": 100,
    "company_site": 30,
    "linkedin_proxycurl": 10,
    "social_profiles": 20,
}

AUTH_DEFAULTS: Final[dict[str, int]] = {
    "login": 10,        # 10 login attempts per minute per IP
    "signup": 5,        # 5 signups per minute per IP
    "refresh": 30,      # 30 refreshes per minute per IP
    "webhook": 100,     # 100 webhook calls per minute per IP
    # Deliberately tight: this endpoint sends mail to an address the caller
    # supplies, so a loose limit turns it into a way to spam a third party
    # from our domain and burn our sending reputation.
    "password_reset": 3,
}


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    current: int
    limit: int
    retry_after_seconds: int = 0
    window_seconds: int = 60


def _key(prefix: str, identifier: str, source: str, window: int) -> str:
    return f"outreach:ratelimit:{prefix}:{identifier}:{source}:{window}"


def limit_for(source: str) -> int:
    """Return the configured per-minute cap for a scraping source."""
    settings = get_settings()
    override = settings.scraping_rate_limits_per_minute.get(source)
    if override is not None:
        return override
    return SCRAPE_DEFAULTS.get(source, 60)


def auth_limit_for(source: str) -> int:
    """Return the configured per-minute cap for an auth endpoint."""
    settings = get_settings()
    override = settings.auth_rate_limits_per_minute.get(source)
    if override is not None:
        return override
    return AUTH_DEFAULTS.get(source, 60)


def check_and_consume(tenant_id: str, source: str, *, limit: int | None = None) -> RateLimitDecision:
    """Scraping rate limit (per tenant)."""
    import time

    cap = limit if limit is not None else limit_for(source)
    window = int(time.time()) // 60
    key = _key("tenant", tenant_id, source, window)

    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 65)
    results = pipe.execute()
    current = int(results[0])

    if current > cap:
        retry_after = 60 - (int(time.time()) % 60)
        return RateLimitDecision(
            allowed=False, current=current, limit=cap, retry_after_seconds=retry_after, window_seconds=60
        )
    return RateLimitDecision(allowed=True, current=current, limit=cap, retry_after_seconds=0, window_seconds=60)


def check_and_consume_ip(ip: str, source: str, *, limit: int | None = None) -> RateLimitDecision:
    """Auth/webhook rate limit (per IP)."""
    import time

    cap = limit if limit is not None else auth_limit_for(source)
    window = int(time.time()) // 60
    key = _key("ip", ip, source, window)

    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 65)
    results = pipe.execute()
    current = int(results[0])

    if current > cap:
        retry_after = 60 - (int(time.time()) % 60)
        return RateLimitDecision(
            allowed=False, current=current, limit=cap, retry_after_seconds=retry_after, window_seconds=60
        )
    return RateLimitDecision(allowed=True, current=current, limit=cap, retry_after_seconds=0, window_seconds=60)


def reset(tenant_id: str, source: str | None = None) -> int:
    """Clear the counter(s) for a tenant. Useful in tests and for ops."""
    r = get_redis()
    if source is None:
        pattern = f"outreach:ratelimit:tenant:{tenant_id}:*"
        deleted = 0
        for key in r.scan_iter(match=pattern, count=100):
            r.delete(key)
            deleted += 1
        return deleted
    window = int(__import__("time").time()) // 60
    r.delete(_key("tenant", tenant_id, source, window))
    return 1


def reset_ip(ip: str, source: str | None = None) -> int:
    """Clear the counter(s) for an IP."""
    r = get_redis()
    if source is None:
        pattern = f"outreach:ratelimit:ip:{ip}:*"
        deleted = 0
        for key in r.scan_iter(match=pattern, count=100):
            r.delete(key)
            deleted += 1
        return deleted
    window = int(__import__("time").time()) // 60
    r.delete(_key("ip", ip, source, window))
    return 1
