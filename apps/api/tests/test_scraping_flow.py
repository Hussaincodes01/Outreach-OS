"""End-to-end test of the scraping flow.

We mock the `scraping.run_source` boundary so the worker doesn't make
real HTTP calls, but we exercise the full path: HTTP -> Celery (eager)
-> job status -> leads in the DB.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from .conftest import bearer, signup, unique_email

pytestmark = pytest.mark.asyncio


async def test_launch_scrape_creates_job_and_inserts_leads(client: AsyncClient) -> None:
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    token = a["access_token"]

    # Create an ICP.
    resp = await client.post(
        "/v1/icps",
        json={"name": "VP Sales SaaS US", "titles": ["VP Sales"], "geos": ["US"]},
        headers=bearer(token),
    )
    assert resp.status_code == 201, resp.text
    icp_id = resp.json()["id"]

    # Enable the serper source — the worker skips disabled sources.
    resp = await client.patch(
        "/v1/lead-sources/serper",
        json={"is_enabled": True},
        headers=bearer(token),
    )
    assert resp.status_code == 200, resp.text

    # Stub the scraping dispatch to return a fixed list of leads. We
    # patch the symbol imported inside the task module (not the source
    # module) so the worker uses the stub.
    from outreach_os.services.scraping.raw_lead import RawLead

    def fake_run_source(source, *, credentials, icp, config, limit):
        return [
            RawLead(
                source=source,
                first_name="Alex",
                full_name="Alex Doe",
                email="alex@acme-customer.example",
                domain="acme-customer.example",
                company_name="Acme Customer",
            ),
            RawLead(
                source=source,
                first_name="Bob",
                full_name="Bob Smith",
                email="bob@acme-customer.example",
                domain="acme-customer.example",
                company_name="Acme Customer",
            ),
        ]

    with patch("outreach_os.workers.tasks.scrape.scraping.run_source", side_effect=fake_run_source):
        resp = await client.post(
            f"/v1/icps/{icp_id}/scrape",
            json={"icp_id": icp_id, "sources": ["serper"], "requested_count": 10},
            headers=bearer(token),
        )
        assert resp.status_code == 202, resp.text
        job = resp.json()
        assert job["status"] == "pending"
        assert job["sources"] == ["serper"]
        job_id = job["id"]

    # In eager mode the worker runs in-line with the request, so the
    # job is already in a terminal state by the time we GET.
    resp = await client.get(f"/v1/scraping-jobs/{job_id}", headers=bearer(token))
    assert resp.status_code == 200, resp.text
    completed = resp.json()
    assert completed["status"] == "completed"
    assert completed["found_count"] == 2
    assert completed["completed_at"] is not None

    # Leads should be visible.
    resp = await client.get("/v1/leads", headers=bearer(token))
    assert resp.status_code == 200
    page = resp.json()
    print(f"\nDEBUG: leads page = {page}")
    assert page["total"] == 2
    emails = {lead["email"] for lead in page["items"]}
    assert emails == {"alex@acme-customer.example", "bob@acme-customer.example"}


async def test_rerun_dedupes_existing_leads(client: AsyncClient) -> None:
    """Running the same scrape twice should not duplicate leads."""
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    token = a["access_token"]

    resp = await client.post(
        "/v1/icps", json={"name": "ICP-2"}, headers=bearer(token)
    )
    icp_id = resp.json()["id"]

    resp = await client.patch(
        "/v1/lead-sources/serper", json={"is_enabled": True}, headers=bearer(token)
    )
    assert resp.status_code == 200

    from outreach_os.services.scraping.raw_lead import RawLead

    def fake(source, **_):
        return [
            RawLead(
                source=source, first_name="X", email="dup@example.com",
                domain="dup.example.com", company_name="Dup",
            )
        ]

    with patch("outreach_os.workers.tasks.scrape.scraping.run_source", side_effect=fake):
        for _ in range(2):
            resp = await client.post(
                f"/v1/icps/{icp_id}/scrape",
                json={"icp_id": icp_id, "sources": ["serper"], "requested_count": 5},
                headers=bearer(token),
            )
            assert resp.status_code == 202

    resp = await client.get("/v1/leads", headers=bearer(token))
    page = resp.json()
    assert page["total"] == 1
    assert page["items"][0]["email"] == "dup@example.com"


async def test_scrape_with_disabled_source_skips_it(client: AsyncClient) -> None:
    """A disabled source should not be run even if listed in the job."""
    a = await signup(client, email=unique_email(), password="pw-12345-AbCde", tenant_name="Acme")
    token = a["access_token"]

    resp = await client.post("/v1/icps", json={"name": "ICP-3"}, headers=bearer(token))
    icp_id = resp.json()["id"]

    # Disable serper and company_site; enable linkedin_proxycurl so
    # the worker actually has something to run.
    resp = await client.patch(
        "/v1/lead-sources/serper",
        json={"is_enabled": False},
        headers=bearer(token),
    )
    assert resp.status_code == 200
    resp = await client.patch(
        "/v1/lead-sources/company_site",
        json={"is_enabled": False},
        headers=bearer(token),
    )
    assert resp.status_code == 200
    resp = await client.patch(
        "/v1/lead-sources/linkedin_proxycurl",
        json={"is_enabled": True},
        headers=bearer(token),
    )
    assert resp.status_code == 200

    from outreach_os.services.scraping.raw_lead import RawLead

    called_sources: list[str] = []

    def fake(source, **_):
        called_sources.append(source)
        return [
            RawLead(
                source=source, first_name="L", email=f"l@{source}.example",
                domain=f"{source}.example", company_name=source,
            )
        ]

    with patch("outreach_os.workers.tasks.scrape.scraping.run_source", side_effect=fake):
        resp = await client.post(
            f"/v1/icps/{icp_id}/scrape",
            json={"icp_id": icp_id, "sources": ["serper", "linkedin_proxycurl"],
                  "requested_count": 5},
            headers=bearer(token),
        )
        assert resp.status_code == 202
        job = resp.json()
        job_id = job["id"]

    # Only linkedin_proxycurl was actually invoked.
    assert called_sources == ["linkedin_proxycurl"]
    # Re-fetch the job — by the time the POST returns, the worker has
    # already completed (eager mode).
    resp = await client.get(f"/v1/scraping-jobs/{job_id}", headers=bearer(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"
