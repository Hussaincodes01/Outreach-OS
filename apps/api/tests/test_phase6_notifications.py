"""Phase 6 \u2014 audit log + notifications + slack + email digest.

Covers:

- Audit log hash chain (already in Phase 0+1; this just makes sure the
  JSON export endpoint is wired up).
- Audit JSON streaming export.
- Notification publish + WS broadcast.
- Notification preferences upsert.
- Slack webhook CRUD + delivery.
- Email digest worker.

Each test uses the standard test fixture in conftest.py (the DB is
truncated between tests). The Slack client is swapped for a stub.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from outreach_os.core.auth import create_access_token
from outreach_os.core.config import get_settings
from outreach_os.core.db import get_engine, session_scope
from outreach_os.core.mailer import StubMailer, set_mailer_client
from outreach_os.core.slack_client import StubSlackClient, set_slack_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.core.ws_manager import set_ws_manager
from outreach_os.domain.models.notification import Notification
from outreach_os.domain.models.notification_preference import NotificationPreference
from outreach_os.domain.models.slack_webhook import SlackWebhook
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.models.user import AppUser, UserRole
from outreach_os.main import app
from outreach_os.core.audit import write_audit_event
from outreach_os.services.credential_lookup import create_credential
from outreach_os.services.notification_service import publish

# In-memory WS stub.
from outreach_os.core.ws_manager import TenantConnectionManager


@pytest_asyncio.fixture
async def stub_ws() -> TenantConnectionManager:
    """Reset the WS manager between tests so the in-memory dict is empty."""
    m = TenantConnectionManager()
    set_ws_manager(m)
    yield m
    set_ws_manager(None)


@pytest_asyncio.fixture
async def stub_slack() -> StubSlackClient:
    s = StubSlackClient()
    set_slack_client(s)
    yield s
    set_slack_client(None)


# ---------- helpers ----------


async def _make_user_with_tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """Create a tenant + owner; return (tenant_id, user_id, access_token)."""
    settings = get_settings()
    suffix = uuid.uuid4().hex[:8]
    async with session_scope() as session:
        await session.execute(text("SET LOCAL app.current_tenant = ''"))
        tenant = Tenant(
            name=f"Test-{suffix}",
            slug=f"test-{suffix}",
            plan="starter",
            status="active",
        )
        session.add(tenant)
        await session.flush()
        await set_tenant_for_session(session, str(tenant.id))
        from outreach_os.core.auth import hash_password

        user = AppUser(
            tenant_id=tenant.id,
            email=f"owner-{suffix}@example.test",
            password_hash=hash_password("pw-12345-AbCde"),
            role=UserRole.OWNER.value,
        )
        session.add(user)
        await session.flush()
        tid, uid = tenant.id, user.id
    token = create_access_token(user_id=str(uid), tenant_id=str(tid), role="owner")
    return tid, uid, token


# ---------- audit ----------


@pytest.mark.asyncio
async def test_audit_json_export_streams_all_rows(stub_ws):
    tid, uid, token = await _make_user_with_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        for i in range(3):
            await write_audit_event(
                session, action=f"test.event.{i}", target_type="x", target_id=uuid.uuid4()
            )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/v1/audit/export.json",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    body = r.text.strip().splitlines()
    assert len(body) == 3
    for line in body:
        obj = json.loads(line)
        assert "action" in obj
        assert "row_hash" in obj
        assert "prev_hash" in obj
    # Hash chain: the third row's prev_hash should be the second row's row_hash.
    second = json.loads(body[1])
    third = json.loads(body[2])
    assert third["prev_hash"] == second["row_hash"]


@pytest.mark.asyncio
async def test_audit_csv_export_streams_all_rows(stub_ws):
    tid, uid, token = await _make_user_with_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        for i in range(2):
            await write_audit_event(
                session, action=f"csv.{i}", target_type="x", target_id=uuid.uuid4()
            )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/v1/audit/export.csv",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    rows = r.text.strip().splitlines()
    # header + 2 data rows
    assert rows[0].startswith("id,created_at,actor_kind")
    assert len(rows) == 3


# ---------- notifications ----------


@pytest.mark.asyncio
async def test_publish_creates_notification_row(stub_ws, stub_slack):
    tid, uid, _tok = await _make_user_with_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        n = await publish(
            session,
            tenant_id=tid,
            event_key="reply.positive",
            title="Acme replied positively",
            body="Let's meet Tuesday",
            target_type="reply",
            target_id=uuid.uuid4(),
        )
        assert n.id is not None
        assert n.delivered_in_app is True
        # default channel for slack is off
        assert n.delivered_slack is False
        rows = (
            await session.execute(
                select(Notification).where(Notification.tenant_id == tid)
            )
        ).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_publish_broadcasts_to_ws(stub_ws, stub_slack):
    tid, uid, _tok = await _make_user_with_tenant()
    # Simulate one connected client.
    import asyncio
    from fastapi import WebSocket

    class _FakeWS:
        def __init__(self) -> None:
            self.sent: list[dict] = []
            self.accepted = False

        async def accept(self) -> None:
            self.accepted = True

        async def send_json(self, obj) -> None:
            self.sent.append(obj)

        async def receive_text(self) -> str:
            await asyncio.sleep(60)

    fake = _FakeWS()
    await stub_ws.connect(tid, fake)
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        await publish(
            session,
            tenant_id=tid,
            event_key="meeting.confirmed",
            title="Meeting confirmed",
        )
    assert len(fake.sent) == 1
    evt = fake.sent[0]
    assert evt["event_key"] == "meeting.confirmed"
    assert evt["title"] == "Meeting confirmed"


@pytest.mark.asyncio
async def test_notification_list_unread_count(stub_ws, stub_slack):
    tid, uid, token = await _make_user_with_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        for i in range(4):
            await publish(
                session,
                tenant_id=tid,
                event_key="scraping.completed",
                title=f"job {i}",
            )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/v1/notifications",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        page = r.json()
        assert page["total"] == 4
        assert page["unread"] == 4
        assert len(page["items"]) == 4
        r2 = await ac.get(
            "/v1/notifications/unread_count",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.json() == {"unread": 4}
        # Mark the first 2 as read.
        ids = [it["id"] for it in page["items"][:2]]
        r3 = await ac.post(
            "/v1/notifications/mark_read",
            json={"ids": ids},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 200
        assert r3.json() == {"updated": 2}
        r4 = await ac.get(
            "/v1/notifications",
            headers={"Authorization": f"Bearer {token}"},
        )
        page2 = r4.json()
        assert page2["unread"] == 2


@pytest.mark.asyncio
async def test_notification_event_keys_endpoint(stub_ws, stub_slack):
    tid, uid, token = await _make_user_with_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(
            "/v1/notifications/events",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    events = r.json()["events"]
    assert "reply.positive" in events
    assert "meeting.confirmed" in events
    assert "send.failed" in events


# ---------- preferences ----------


@pytest.mark.asyncio
async def test_preference_upsert(stub_ws, stub_slack):
    tid, uid, token = await _make_user_with_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Initially empty.
        r0 = await ac.get(
            "/v1/notification-preferences",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r0.json()["items"] == []
        # Upsert one.
        r1 = await ac.put(
            "/v1/notification-preferences",
            json={
                "event_key": "reply.positive",
                "channel_in_app": True,
                "channel_email_digest": True,
                "channel_slack": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200
        assert r1.json()["event_key"] == "reply.positive"
        assert r1.json()["channel_email_digest"] is True
        # Update the same key \u2014 only the email toggle changes.
        r2 = await ac.put(
            "/v1/notification-preferences",
            json={
                "event_key": "reply.positive",
                "channel_in_app": True,
                "channel_email_digest": False,
                "channel_slack": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.json()["channel_email_digest"] is False
        assert r2.json()["channel_slack"] is True
        # Now the list returns the one row.
        r3 = await ac.get(
            "/v1/notification-preferences",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert len(r3.json()["items"]) == 1


@pytest.mark.asyncio
async def test_publish_with_slack_pref_fans_out(stub_ws, stub_slack):
    tid, uid, _tok = await _make_user_with_tenant()
    # Wire up a webhook + a preference that enables slack.
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        cred = await create_credential(
            session,
            tenant_id=tid,
            kind="slack_webhook",
            label="default",
            plaintext={"webhook_url": "https://hooks.slack.com/services/T0/B0/XXX"},
        )
        hook = SlackWebhook(
            tenant_id=tid,
            name="default",
            webhook_url_credential_id=cred.id,
            channel="#outreach",
            status="active",
        )
        session.add(hook)
        pref = NotificationPreference(
            tenant_id=tid,
            event_key="reply.positive",
            channel_in_app=True,
            channel_email_digest=False,
            channel_slack=True,
        )
        session.add(pref)
        await session.flush()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        n = await publish(
            session,
            tenant_id=tid,
            event_key="reply.positive",
            title="Acme replied positively",
        )
        assert n.delivered_slack is True
    assert len(stub_slack.calls) == 1
    call = stub_slack.calls[0]
    assert call["webhook_url"] == "https://hooks.slack.com/services/T0/B0/XXX"
    assert call["payload"]["channel"] == "#outreach"
    assert "Acme replied" in call["payload"]["text"]


@pytest.mark.asyncio
async def test_publish_with_no_slack_pref_doesnt_call(stub_ws, stub_slack):
    tid, uid, _tok = await _make_user_with_tenant()
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid))
        await publish(
            session,
            tenant_id=tid,
            event_key="meeting.proposed",
            title="Proposal",
        )
    assert stub_slack.calls == []


# ---------- slack webhooks ----------


@pytest.mark.asyncio
async def test_slack_webhook_crud(stub_ws, stub_slack):
    tid, uid, token = await _make_user_with_tenant()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/slack-webhooks",
            json={
                "name": "default",
                "webhook_url": "https://hooks.slack.com/services/T0/B0/YYY",
                "channel": "#alerts",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201
        h = r.json()
        assert h["name"] == "default"
        assert h["channel"] == "#alerts"
        assert h["status"] == "active"
        hid = h["id"]
        # List
        r2 = await ac.get(
            "/v1/slack-webhooks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert len(r2.json()) == 1
        # Pause
        r3 = await ac.post(
            f"/v1/slack-webhooks/{hid}/pause",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.json()["status"] == "paused"
        # Resume
        r4 = await ac.post(
            f"/v1/slack-webhooks/{hid}/resume",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r4.json()["status"] == "active"
        # Delete
        r5 = await ac.delete(
            f"/v1/slack-webhooks/{hid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r5.status_code == 204
        r6 = await ac.get(
            "/v1/slack-webhooks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r6.json() == []


# ---------- email digest ----------


@pytest.mark.asyncio
async def test_email_digest_groups_by_tenant_and_sends(stub_ws, stub_slack):
    """Run the digest task synchronously and assert it groups + sends."""
    mailer = StubMailer()
    set_mailer_client(mailer)
    try:
        tid, uid, _tok = await _make_user_with_tenant()
        async with session_scope() as session:
            await set_tenant_for_session(session, str(tid))
            for i in range(3):
                await publish(
                    session,
                    tenant_id=tid,
                    event_key="scraping.completed",
                    title=f"job {i}",
                    severity="success",
                )
        from outreach_os.workers.tasks.notifications import (
            _send_email_digest_async,
        )
        result = await _send_email_digest_async()
        assert result["groups"] == 1
        assert result["items_sent"] == 3
        # One digest email was sent.
        assert len(mailer.sent) == 1
        msg = mailer.sent[0]
        assert "Daily digest" in msg.subject
        assert "3 updates" in msg.subject
        assert "job 0" in msg.body_text
        # Marked as delivered.
        async with session_scope() as session:
            await set_tenant_for_session(session, str(tid))
            undelivered = (
                await session.execute(
                    select(Notification).where(
                        Notification.tenant_id == tid,
                        Notification.delivered_email.is_(False),
                    )
                )
            ).scalars().all()
            assert undelivered == []
    finally:
        set_mailer_client(None)


# ---------- RLS isolation ----------


@pytest.mark.asyncio
async def test_notifications_isolated_by_tenant(stub_ws, stub_slack):
    """A notification for tenant A must not appear in tenant B's list."""
    tid_a, uid_a, tok_a = await _make_user_with_tenant()
    tid_b, uid_b, tok_b = await _make_user_with_tenant()
    assert tid_a != tid_b
    async with session_scope() as session:
        await set_tenant_for_session(session, str(tid_a))
        await publish(
            session,
            tenant_id=tid_a,
            event_key="reply.positive",
            title="only for A",
        )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r_a = await ac.get(
            "/v1/notifications",
            headers={"Authorization": f"Bearer {tok_a}"},
        )
        r_b = await ac.get(
            "/v1/notifications",
            headers={"Authorization": f"Bearer {tok_b}"},
        )
    assert r_a.json()["total"] == 1
    assert r_b.json()["total"] == 0
