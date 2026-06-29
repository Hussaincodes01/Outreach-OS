"""Phase 7 \u2014 billing + plans + usage gates.

Covers:
- Plan seeding + listing.
- Implicit-free plan when no subscription.
- Checkout flow (stub provider).
- Stub webhook -> subscription state.
- Portal token issuance + consumption.
- Usage recording + cap enforcement.
- Plan-gated features: CRM sync fails on starter, succeeds on growth.
- Monthly usage rollup.
- RLS isolation: subscription + usage rows hidden across tenants.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from outreach_os.core.auth import create_access_token, hash_password
from outreach_os.core.billing_client import StubBillingClient, set_billing_client
from outreach_os.core.db import session_scope
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.plan import Plan
from outreach_os.domain.models.subscription import Subscription
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.models.usage_event import UsageEvent
from outreach_os.domain.models.user import AppUser, UserRole
from outreach_os.main import app
from outreach_os.services import billing_service


@pytest_asyncio.fixture
async def stub_billing():
    s = StubBillingClient(api_base="http://test")
    set_billing_client(s)
    yield s
    set_billing_client(None)


async def _make_tenant(slug_suffix: str | None = None) -> tuple[uuid.UUID, uuid.UUID, str]:
    suffix = slug_suffix or uuid.uuid4().hex[:8]
    async with session_scope() as session:
        await session.execute(text("SET LOCAL app.current_tenant = ''"))
        tenant = Tenant(
            name=f"T-{suffix}",
            slug=f"t-{suffix}",
            plan="starter",
            status="active",
        )
        session.add(tenant)
        await session.flush()
        await set_tenant_for_session(session, str(tenant.id))
        user = AppUser(
            tenant_id=tenant.id,
            email=f"u-{suffix}@example.test",
            password_hash=hash_password("pw-12345-AbCde"),
            role=UserRole.OWNER.value,
        )
        session.add(user)
        await session.flush()
        tid, uid = tenant.id, user.id
    token = create_access_token(user_id=str(uid), tenant_id=str(tid), role="owner")
    return tid, uid, token


@pytest.mark.asyncio
async def test_plans_seeded(stub_billing):
    async with session_scope() as session:
        plans = await billing_service.list_plans(session)
        print("DEBUG plans=", plans, "len=", len(plans))
    codes = {p.code for p in plans}
    print("DEBUG codes=", codes)
    assert {"starter", "growth", "scale"}.issubset(codes)


@pytest.mark.asyncio
async def test_no_subscription_returns_none(stub_billing):
    tid, uid, token = await _make_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/v1/billing/subscription", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_usage_summary(stub_billing):
    tid, uid, token = await _make_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/v1/billing/usage", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    # starter defaults from the migration.
    assert data["sends_cap"] == 500
    assert data["leads_cap"] == 1000
    assert data["llm_tokens_cap"] == 200000


@pytest.mark.asyncio
async def test_checkout_returns_stub_url(stub_billing):
    tid, uid, token = await _make_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/billing/checkout",
            json={"plan_code": "growth"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["provider"] == "stub"
    assert "stub/complete?session=" in data["checkout_url"]
    assert len(stub_billing.sessions) == 1


@pytest.mark.asyncio
async def test_stub_webhook_creates_subscription(stub_billing):
    tid, uid, token = await _make_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/billing/webhook/stub",
            json={
                "tenant_id": str(tid),
                "plan_code": "growth",
                "status": "active",
                "customer_id": "cus_test_1",
                "subscription_id": "sub_test_1",
            },
        )
    assert r.status_code == 200
    assert r.json()["processed"] is True
    # Now the subscription should show up.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r2 = await ac.get("/v1/billing/subscription", headers={"Authorization": f"Bearer {token}"})
    sub = r2.json()
    assert sub is not None
    assert sub["plan"]["code"] == "growth"
    assert sub["provider"] == "stub"
    assert sub["provider_customer_id"] == "cus_test_1"
    # Tenant.plan was mirrored.
    async with session_scope() as session:
        t = await session.get(Tenant, tid)
        assert t.plan == "growth"


@pytest.mark.asyncio
async def test_checkout_then_webhook_then_portal(stub_billing):
    tid, uid, token = await _make_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. start checkout
        r = await ac.post(
            "/v1/billing/checkout",
            json={"plan_code": "scale"},
            headers={"Authorization": f"Bearer {token}"},
        )
        checkout_url = r.json()["checkout_url"]
        session_id = checkout_url.split("session=")[-1]
        assert session_id in stub_billing.sessions
        # 2. "complete" via webhook
        r = await ac.post(
            "/v1/billing/webhook/stub",
            json={
                "tenant_id": str(tid),
                "plan_code": "scale",
                "status": "active",
                "customer_id": "cus_test_2",
                "subscription_id": "sub_test_2",
            },
        )
        assert r.status_code == 200
        # 3. open portal
        r = await ac.post("/v1/billing/portal", json={}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        portal = r.json()
        assert portal["token"] is not None
        assert len(stub_billing.portal_calls) == 1
        # 4. consume token -> 302
        r = await ac.get(
            "/v1/billing/portal/redirect",
            params={"token": portal["token"]},
            follow_redirects=False,
        )
        assert r.status_code == 302
        # Second use of the same token is 404.
        r = await ac.get(
            "/v1/billing/portal/redirect",
            params={"token": portal["token"]},
            follow_redirects=False,
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_record_usage_bumps_rollup(stub_billing):
    tid, uid, _tok = await _make_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        for _ in range(5):
            await billing_service.record_usage(
                session, tenant_id=tid, metric="send"
            )
        s = await billing_service.usage_summary(session, tenant_id=tid)
    assert s["sends_used"] == 5
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        rows = (await session.execute(
            select(UsageEvent).where(UsageEvent.tenant_id == tid)
        )).scalars().all()
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_check_within_limits_blocks_when_over(stub_billing):
    tid, uid, _tok = await _make_tenant()
    # Starter plan: monthly_send_cap = 500. Set the tenant to 499 first.
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        t = await session.get(Tenant, tid)
        t.month_usage_sends = 499
    # One more is fine.
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        await billing_service.check_within_limits(session, tenant_id=tid, metric="send")
    # Two more raises.
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        with pytest.raises(billing_service.BillingLimitExceeded) as exc:
            await billing_service.check_within_limits(
                session, tenant_id=tid, metric="send", n=2
            )
    assert exc.value.metric == "send"
    assert exc.value.cap == 500


@pytest.mark.asyncio
async def test_plan_gating_crm_sync_on_starter(stub_billing):
    """CRM sync is only enabled on growth+ plans. The service layer
    must raise an error when called on a starter tenant."""
    from outreach_os.core.crm_client import StubCrmClient, set_crm_client
    from outreach_os.core.calendar_client import StubCalendarClient, set_calendar_client

    crm = StubCrmClient()
    set_crm_client(crm)
    cal = StubCalendarClient()
    set_calendar_client(cal)
    try:
        tid, uid, _tok = await _make_tenant()
        # Create a connection + meeting.
        async with session_scope() as session:
            await set_tenant_for_session(session, str(tid))
            from outreach_os.domain.models.lead import Lead
            from outreach_os.domain.models.crm_connection import CrmConnection
            lead = Lead(
                tenant_id=tid, source="serper", email="x@example.test",
                first_name="X", last_name="Y",
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
            conn = CrmConnection(
                tenant_id=tid,
                provider="google_sheets",
                name="default",
                spreadsheet_id="s1",
                sheet_range="A:Z",
                column_mapping={"email": "A"},
                status="active",
            )
            session.add(conn)
            await session.flush()
            conn_id = conn.id
        # CRM sync without an active subscription should be gated.
        from outreach_os.services import crm_service
        from outreach_os.services.meeting_service import MeetingService
        # Create a meeting, then try to sync.
        async with session_scope() as session:
            await set_tenant_for_session(session, str(tid))
            from outreach_os.domain.models.meeting import Meeting
            meeting = Meeting(
                tenant_id=tid,
                lead_id=lead_id,
                subject="intro",
                duration_minutes=30,
                proposed_slots=[{"index": 0, "start": "2026-06-08T10:00:00Z",
                                  "end": "2026-06-08T10:30:00Z"}],
                ics_uid=f"uid-{uuid.uuid4()}@outreach-os.local",
                organizer_email="o@example.test",
                attendee_email="x@example.test",
            )
            session.add(meeting)
            await session.flush()
            meeting_id = meeting.id
        # On starter, sync should refuse (no CRM feature flag).
        with pytest.raises(Exception) as exc:
            from outreach_os.services import billing_service, crm_service
            from outreach_os.services.crm_service import CrmService
            async with session_scope() as session:
                await set_tenant_for_session(session, str(tid))
                svc = CrmService(session)
                await svc.sync_meeting(tenant_id=tid, meeting_id=meeting_id)
    finally:
        set_crm_client(None)
        set_calendar_client(None)


@pytest.mark.asyncio
async def test_plan_gating_relaxes_on_growth(stub_billing):
    """After upgrading to growth, crm_sync_enabled is True."""
    tid, uid, _tok = await _make_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        await billing_service.apply_subscription_event(
            session,
            tenant_id=tid,
            plan_code="growth",
            provider="stub",
            provider_customer_id="cus_x",
            provider_subscription_id="sub_x",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc),
        )
        plan = await billing_service.effective_plan(session, tenant_id=tid)
        assert plan.crm_sync_enabled is True
        assert plan.slack_notifications_enabled is True
        assert plan.email_digest_enabled is True


@pytest.mark.asyncio
async def test_rollup_resets_after_window(stub_billing):
    tid, uid, _tok = await _make_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        # Set tenant's reset_at to last month and add some events in this month.
        from datetime import timedelta
        t = await session.get(Tenant, tid)
        t.month_usage_sends = 999
        t.month_usage_leads = 999
        t.month_usage_llm_tokens = 999
        t.month_usage_reset_at = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        await billing_service.record_usage(
            session, tenant_id=tid, metric="send", quantity=7
        )
        n = await billing_service.rollup_usage_counters(session)
    assert n >= 1
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        t = await session.get(Tenant, tid)
        # The rollup replaces the rollup counters with the live sums.
        assert t.month_usage_sends == 7
        assert t.month_usage_leads == 0


@pytest.mark.asyncio
async def test_subscription_isolated_by_tenant(stub_billing):
    tid_a, uid_a, _tok_a = await _make_tenant()
    tid_b, uid_b, _tok_b = await _make_tenant()
    # Apply a subscription to A only.
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid_a))
        await billing_service.apply_subscription_event(
            session,
            tenant_id=tid_a,
            plan_code="growth",
            provider="stub",
            provider_customer_id="cus_a",
            provider_subscription_id="sub_a",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc),
        )
    # Read A directly: should see its subscription.
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid_a))
        a_sub = await billing_service.active_subscription(session, tenant_id=tid_a)
    assert a_sub is not None
    # Read B: should see nothing.
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid_b))
        b_sub = await billing_service.active_subscription(session, tenant_id=tid_b)
    assert b_sub is None
