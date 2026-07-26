"""RLS isolation tests for the Phase 2 tables (icp, lead, lead_source,
scraping_job, proxy). Mirrors the Phase 0/1 `test_tenancy_isolation.py`
pattern: signup two tenants, create rows as A, verify B sees nothing.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from outreach_os.domain.schemas.lead_scraping import VALID_SOURCES

from .conftest import bearer, signup, unique_email

pytestmark = pytest.mark.asyncio


async def _create_icp(client: AsyncClient, token: str, name: str = "My ICP") -> str:
    resp = await client.post(
        "/v1/icps",
        json={
            "name": name,
            "industries": ["SaaS"],
            "titles": ["VP Sales"],
            "geos": ["US"],
        },
        headers=bearer(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_list_icps_isolated_per_tenant(client: AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    b = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Globex")
    a_id = await _create_icp(client, a["access_token"], name="Acme ICP")

    resp = await client.get("/v1/icps", headers=bearer(a["access_token"]))
    assert resp.status_code == 200
    a_list = resp.json()
    assert len(a_list) == 1
    assert a_list[0]["id"] == a_id

    resp = await client.get("/v1/icps", headers=bearer(b["access_token"]))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_other_tenant_icp_returns_404(client: AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    b = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Globex")
    a_id = await _create_icp(client, a["access_token"])

    # B cannot read A's ICP — must look like "not found", never "forbidden".
    resp = await client.get(f"/v1/icps/{a_id}", headers=bearer(b["access_token"]))
    assert resp.status_code == 404


async def test_delete_other_tenant_icp_returns_404(client: AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    b = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Globex")
    a_id = await _create_icp(client, a["access_token"])

    resp = await client.delete(f"/v1/icps/{a_id}", headers=bearer(b["access_token"]))
    assert resp.status_code == 404

    # A can still see its ICP.
    resp = await client.get(f"/v1/icps/{a_id}", headers=bearer(a["access_token"]))
    assert resp.status_code == 200


async def test_lead_sources_autoseed_isolated(client: AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    b = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Globex")
    # Autoseed covers every known source; assert against the single source of
    # truth so adding a source doesn't silently leave this test behind.
    expected = set(VALID_SOURCES)
    resp = await client.get("/v1/lead-sources", headers=bearer(a["access_token"]))
    assert resp.status_code == 200
    sources = {r["source"] for r in resp.json()}
    assert sources == expected

    # B sees its own set (autoseeded independently).
    resp = await client.get("/v1/lead-sources", headers=bearer(b["access_token"]))
    assert resp.status_code == 200
    assert {r["source"] for r in resp.json()} == expected


async def test_list_leads_isolated_per_tenant(client: AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    b = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Globex")

    # Direct insert via the lead_service API path (bypasses /v1/leads which
    # has no POST; the worker is what writes leads in production). We use
    # get_scoped_db indirectly by going through the service module.

    from outreach_os.core.db import get_session_factory
    from outreach_os.core.tenancy import set_tenant_for_session
    from outreach_os.services import lead_service
    from outreach_os.services.scraping.raw_lead import RawLead

    factory = get_session_factory()
    for token_pair, sample_domain in (
        (a, "acmecustomer.example"),
        (b, "globexcustomer.example"),
    ):
        async with factory() as session, session.begin():
            tenant_uuid = __import__("uuid").UUID(token_pair["tenant_id"])
            await set_tenant_for_session(session, str(tenant_uuid))
            await lead_service.insert_leads(
                session,
                tenant_id=tenant_uuid,
                job_id=None,
                raw_leads=[
                    RawLead(
                        source="company_site",
                        first_name="Alex",
                        email=f"alex@{sample_domain}",
                        domain=sample_domain,
                        company_name="Sample",
                    )
                ],
            )

    # Each tenant sees only its own lead.
    resp = await client.get("/v1/leads", headers=bearer(a["access_token"]))
    assert resp.status_code == 200
    a_items = resp.json()["items"]
    assert len(a_items) == 1
    assert a_items[0]["domain"] == "acmecustomer.example"

    resp = await client.get("/v1/leads", headers=bearer(b["access_token"]))
    assert resp.status_code == 200
    b_items = resp.json()["items"]
    assert len(b_items) == 1
    assert b_items[0]["domain"] == "globexcustomer.example"


async def test_proxy_isolated_per_tenant(client: AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    b = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Globex")

    resp = await client.post(
        "/v1/proxies",
        json={"label": "myproxy", "protocol": "http", "host": "10.0.0.1", "port": 8080},
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get("/v1/proxies", headers=bearer(b["access_token"]))
    assert resp.status_code == 200
    assert resp.json() == []
