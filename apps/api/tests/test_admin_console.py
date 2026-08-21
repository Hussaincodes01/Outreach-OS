"""Platform admin console.

The console is the one place that reads across tenants, so most of these
assert who CANNOT reach it. A tenant owner is an admin of their own workspace;
that must never imply visibility of anyone else's customers.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from outreach_os.core.db import get_session_factory
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.user import AppUser
from tests.conftest import bearer, signup, unique_email

pytestmark = pytest.mark.asyncio

_PASSWORD = "correct-horse-battery-staple"


async def _make_staff(tenant_id: str, user_id: str) -> None:
    """Promote a user to platform staff.

    Done by direct statement on purpose — there is no API for this, because
    granting cross-customer visibility should be a deliberate database act.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, tenant_id)
        row = (
            await session.execute(select(AppUser).where(AppUser.id == user_id))
        ).scalar_one()
        row.is_platform_admin = True


# --- access control ---------------------------------------------------------


async def test_ordinary_owner_cannot_reach_the_console(client) -> None:
    """The owner of a workspace is not staff."""
    a = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Customer Co"
    )
    headers = bearer(a["access_token"])
    for path in ("/v1/admin/customers", "/v1/admin/stats"):
        resp = await client.get(path, headers=headers)
        # 404 rather than 403: confirming the console exists tells a probing
        # tenant owner there is something worth attacking.
        assert resp.status_code == 404, path


async def test_console_requires_authentication(client) -> None:
    assert (await client.get("/v1/admin/customers")).status_code == 401


async def test_suspend_is_refused_to_non_staff(client) -> None:
    a = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="A Co"
    )
    b = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="B Co"
    )
    resp = await client.patch(
        f"/v1/admin/customers/{b['tenant_id']}/status",
        json={"status": "suspended"},
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 404


async def test_staff_flag_is_not_settable_through_the_api(client) -> None:
    """No endpoint may grant platform access — otherwise a compromised owner
    account escalates to every customer's data."""
    a = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Escalate Co"
    )
    headers = bearer(a["access_token"])
    # The signup response and /me must never echo it as writable, and no
    # user-management route accepts it.
    resp = await client.post(
        "/v1/users",
        json={
            "email": unique_email(),
            "password": _PASSWORD,
            "role": "owner",
            "is_platform_admin": True,
        },
        headers=headers,
    )
    if resp.status_code in (200, 201):
        created = resp.json()
        assert created.get("is_platform_admin") in (False, None)
    me = (await client.get("/v1/auth/me", headers=headers)).json()
    assert me["is_platform_admin"] is False


# --- the console itself -----------------------------------------------------


async def test_staff_sees_every_customer(client) -> None:
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Operator"
    )
    await _make_staff(staff["tenant_id"], staff["user_id"])
    other = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Zebra Industries"
    )

    resp = await client.get(
        "/v1/admin/customers", headers=bearer(staff["access_token"])
    )
    assert resp.status_code == 200, resp.text
    names = {c["name"] for c in resp.json()["items"]}
    assert "Operator" in names
    assert "Zebra Industries" in names
    assert other["tenant_id"] in {c["tenant_id"] for c in resp.json()["items"]}


async def test_me_reports_staff_so_the_ui_can_show_the_link(client) -> None:
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Op2"
    )
    headers = bearer(staff["access_token"])
    assert (await client.get("/v1/auth/me", headers=headers)).json()[
        "is_platform_admin"
    ] is False

    await _make_staff(staff["tenant_id"], staff["user_id"])
    assert (await client.get("/v1/auth/me", headers=headers)).json()[
        "is_platform_admin"
    ] is True


async def test_customer_rows_carry_counts_and_plan(client) -> None:
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Op3"
    )
    await _make_staff(staff["tenant_id"], staff["user_id"])
    resp = await client.get(
        "/v1/admin/customers?q=Op3", headers=bearer(staff["access_token"])
    )
    row = next(c for c in resp.json()["items"] if c["name"] == "Op3")
    # One owner was created at signup.
    assert row["user_count"] == 1
    assert row["lead_count"] == 0
    assert row["plan"]
    assert row["status"] == "active"
    # No subscription bought yet — a plan label is not a subscription.
    assert row["subscription_status"] is None


async def test_search_filters_by_name(client) -> None:
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Op4"
    )
    await _make_staff(staff["tenant_id"], staff["user_id"])
    await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Findable Widgets"
    )
    resp = await client.get(
        "/v1/admin/customers?q=findable", headers=bearer(staff["access_token"])
    )
    names = {c["name"] for c in resp.json()["items"]}
    assert names == {"Findable Widgets"}


async def test_stats_count_workspaces(client) -> None:
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Op5"
    )
    await _make_staff(staff["tenant_id"], staff["user_id"])
    body = (
        await client.get("/v1/admin/stats", headers=bearer(staff["access_token"]))
    ).json()
    assert body["total_customers"] >= 1
    assert body["active_customers"] >= 1
    # Nobody has paid in this test database.
    assert body["paying_customers"] == 0
    assert body["mrr_cents"] == 0
    assert body["signups_last_30d"] >= 1


async def test_suspend_and_reactivate(client) -> None:
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Op6"
    )
    await _make_staff(staff["tenant_id"], staff["user_id"])
    victim = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Naughty Co"
    )
    headers = bearer(staff["access_token"])

    resp = await client.patch(
        f"/v1/admin/customers/{victim['tenant_id']}/status",
        json={"status": "suspended"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"

    resp = await client.patch(
        f"/v1/admin/customers/{victim['tenant_id']}/status",
        json={"status": "active"},
        headers=headers,
    )
    assert resp.json()["status"] == "active"


async def test_invalid_status_is_rejected(client) -> None:
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Op7"
    )
    await _make_staff(staff["tenant_id"], staff["user_id"])
    resp = await client.patch(
        f"/v1/admin/customers/{staff['tenant_id']}/status",
        json={"status": "deleted-forever"},
        headers=bearer(staff["access_token"]),
    )
    assert resp.status_code == 422


async def test_operator_actions_are_audited(client) -> None:
    """Suspending a customer is a consequential act; it must be traceable."""
    staff = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Op8"
    )
    await _make_staff(staff["tenant_id"], staff["user_id"])
    victim = await signup(
        client, email=unique_email(), password=_PASSWORD, tenant_name="Audited Co"
    )
    headers = bearer(staff["access_token"])
    await client.patch(
        f"/v1/admin/customers/{victim['tenant_id']}/status",
        json={"status": "suspended"},
        headers=headers,
    )
    audit = (await client.get("/v1/audit?limit=50", headers=headers)).json()
    actions = [e["action"] for e in audit["items"]]
    assert "admin.tenant_status_changed" in actions
