"""Tests for the Redis-backed per-tenant, per-source rate limiter."""
from __future__ import annotations

import pytest

from outreach_os.core import rate_limit
from outreach_os.core.redis_client import get_redis, reset_for_tests

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_redis():
    """Clear the rate-limit keys for a synthetic tenant before each test."""
    r = get_redis()
    for key in r.scan_iter(match="outreach:ratelimit:*", count=100):
        r.delete(key)
    yield
    reset_for_tests()


async def test_first_request_is_allowed() -> None:
    decision = rate_limit.check_and_consume("tenant-x", "serper")
    assert decision.allowed
    assert decision.current == 1
    assert decision.limit == 100  # default for serper


async def test_blocked_once_over_limit() -> None:
    """Hitting the cap exactly is allowed; one over is blocked."""
    cap = 3
    for i in range(1, cap + 1):
        d = rate_limit.check_and_consume("tenant-y", "company_site", limit=cap)
        assert d.allowed, f"call {i} unexpectedly blocked"
        assert d.current == i
    # 4th call must be blocked.
    d = rate_limit.check_and_consume("tenant-y", "company_site", limit=cap)
    assert not d.allowed
    assert d.retry_after_seconds > 0
    assert d.retry_after_seconds <= 60


async def test_tenants_isolated() -> None:
    """Tenant A's usage does not affect tenant B."""
    cap = 1
    a = rate_limit.check_and_consume("tenant-a", "serper", limit=cap)
    assert a.allowed
    b = rate_limit.check_and_consume("tenant-b", "serper", limit=cap)
    assert b.allowed
    # A is now blocked; B is not.
    a2 = rate_limit.check_and_consume("tenant-a", "serper", limit=cap)
    assert not a2.allowed
    b2 = rate_limit.check_and_consume("tenant-b", "serper", limit=cap)
    assert not b2.allowed  # B's first call already used its cap
    # C starts fresh.
    c = rate_limit.check_and_consume("tenant-c", "serper", limit=cap)
    assert c.allowed


async def test_sources_have_separate_counters() -> None:
    """serper and company_site counters are independent."""
    cap = 1
    s = rate_limit.check_and_consume("tenant-z", "serper", limit=cap)
    assert s.allowed
    s2 = rate_limit.check_and_consume("tenant-z", "serper", limit=cap)
    assert not s2.allowed
    # company_site is a separate counter.
    cs = rate_limit.check_and_consume("tenant-z", "company_site", limit=cap)
    assert cs.allowed


async def test_default_limits_match_plan() -> None:
    """The defaults from the plan: 100/min Serper, 30/min company site,
    10/min LinkedIn-via-Proxycurl."""
    assert rate_limit.limit_for("serper") == 100
    assert rate_limit.limit_for("company_site") == 30
    assert rate_limit.limit_for("linkedin_proxycurl") == 10
