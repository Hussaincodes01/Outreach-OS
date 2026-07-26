"""Phase 3 — RLS isolation tests for campaign + knowledge + draft tables.

Every multi-tenant table added in 0004 must (a) be created, (b) deny
cross-tenant reads, (c) deny cross-tenant writes implicitly via RLS, and
(d) be deletable only by its own tenant.
"""
from __future__ import annotations

import pytest

from outreach_os.core.llm import set_llm_client
from tests.conftest import bearer, signup
from tests.fake_llm import FakeLLMClient


@pytest.fixture(autouse=True)
def fake_llm():
    """Install the deterministic fake for the duration of each test so
    the knowledge endpoint's RAGService doesn't hit the real OpenAI API."""
    fake = FakeLLMClient()
    set_llm_client(fake)
    yield fake
    set_llm_client(None)


async def test_campaigns_are_isolated_per_tenant(client):
    a = await signup(client, email="a-camp@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-camp")
    b = await signup(client, email="b-camp@acme-customer.example", password="pw-12345-AbCde", tenant_name="B-camp")

    # Tenant A creates one campaign.
    r = await client.post(
        "/v1/campaigns",
        headers=bearer(a["access_token"]),
        json={
            "name": "A-only",
            "style_sample_emails": ["Hi {first_name}, this is a test."],
            "steps": [
                {
                    "step_number": 1,
                    "delay_days": 0,
                    "subject_template": "Quick question",
                    "goal": "open a conversation",
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    a_camp_id = r.json()["id"]

    # Tenant A sees exactly 1.
    r = await client.get("/v1/campaigns", headers=bearer(a["access_token"]))
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Tenant B sees 0.
    r = await client.get("/v1/campaigns", headers=bearer(b["access_token"]))
    assert r.status_code == 200
    assert r.json() == []

    # Tenant B cannot fetch tenant A's campaign by id.
    r = await client.get(f"/v1/campaigns/{a_camp_id}", headers=bearer(b["access_token"]))
    assert r.status_code == 404

    # Tenant B cannot update or delete tenant A's campaign.
    r = await client.patch(
        f"/v1/campaigns/{a_camp_id}",
        headers=bearer(b["access_token"]),
        json={"name": "B-tries"},
    )
    assert r.status_code == 404
    r = await client.delete(f"/v1/campaigns/{a_camp_id}", headers=bearer(b["access_token"]))
    assert r.status_code == 404

    # Tenant A's campaign is still there.
    r = await client.get(f"/v1/campaigns/{a_camp_id}", headers=bearer(a["access_token"]))
    assert r.status_code == 200
    assert r.json()["name"] == "A-only"


async def test_knowledge_items_are_isolated_per_tenant(client):
    a = await signup(client, email="a-kb@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-kb")
    b = await signup(client, email="b-kb@acme-customer.example", password="pw-12345-AbCde", tenant_name="B-kb")

    r = await client.post(
        "/v1/knowledge",
        headers=bearer(a["access_token"]),
        json={"title": "Acme case study", "body": "We helped Acme grow 3x in Q3."},
    )
    assert r.status_code == 201
    a_item_id = r.json()["id"]

    # Tenant A sees it.
    r = await client.get("/v1/knowledge", headers=bearer(a["access_token"]))
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # Tenant B sees 0.
    r = await client.get("/v1/knowledge", headers=bearer(b["access_token"]))
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # Tenant B cannot fetch by id.
    r = await client.get(f"/v1/knowledge/{a_item_id}", headers=bearer(b["access_token"]))
    assert r.status_code == 404

    # Tenant B cannot delete tenant A's item.
    r = await client.delete(f"/v1/knowledge/{a_item_id}", headers=bearer(b["access_token"]))
    assert r.status_code == 404

    # Tenant A's item is still there.
    r = await client.get(f"/v1/knowledge/{a_item_id}", headers=bearer(a["access_token"]))
    assert r.status_code == 200


async def test_campaign_step_replace_is_scoped(client):
    a = await signup(client, email="a-step@acme-customer.example", password="pw-12345-AbCde", tenant_name="A-step")
    r = await client.post(
        "/v1/campaigns",
        headers=bearer(a["access_token"]),
        json={
            "name": "step-test",
            "steps": [
                {"step_number": 1, "delay_days": 0, "subject_template": "S1"},
                {"step_number": 2, "delay_days": 3, "subject_template": "S2"},
            ],
        },
    )
    assert r.status_code == 201
    camp_id = r.json()["id"]
    assert len(r.json()["steps"]) == 2

    # Replace with 1 step.
    r = await client.put(
        f"/v1/campaigns/{camp_id}/steps",
        headers=bearer(a["access_token"]),
        json=[
            {"step_number": 1, "delay_days": 0, "subject_template": "S1-new", "goal": "open"},
        ],
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["subject_template"] == "S1-new"


async def test_duplicate_step_number_rejected(client):
    a = await signup(client, email="dup-step@acme-customer.example", password="pw-12345-AbCde", tenant_name="Dup")
    r = await client.post(
        "/v1/campaigns",
        headers=bearer(a["access_token"]),
        json={
            "name": "dup-test",
            "steps": [
                {"step_number": 1, "delay_days": 0, "subject_template": "S1"},
                {"step_number": 1, "delay_days": 3, "subject_template": "S1-bis"},
            ],
        },
    )
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"].lower()


async def test_duplicate_campaign_name_rejected(client):
    a = await signup(client, email="dup-name@acme-customer.example", password="pw-12345-AbCde", tenant_name="DupN")
    payload = {"name": "Same Name", "steps": []}
    r = await client.post("/v1/campaigns", headers=bearer(a["access_token"]), json=payload)
    assert r.status_code == 201
    r = await client.post("/v1/campaigns", headers=bearer(a["access_token"]), json=payload)
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"].lower()
