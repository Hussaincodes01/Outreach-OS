"""Single-user build: no billing, plans, admin console, or team users."""
from __future__ import annotations

import pathlib

import httpx
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "outreach_os"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/billing/plans"),
        ("get", "/v1/billing/subscription"),
        ("get", "/v1/admin/customers"),
        ("get", "/v1/admin/stats"),
        ("get", "/v1/users"),
    ],
)
async def test_saas_routes_are_gone(client: httpx.AsyncClient, method: str, path: str) -> None:
    resp = await getattr(client, method)(path)
    assert resp.status_code in (404, 405), f"{path} -> {resp.status_code}"


def test_no_billing_code_left() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if "billing_service" in p.read_text(encoding="utf-8")
        or "require_platform_admin" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


async def test_lead_create_has_no_plan_cap(client: httpx.AsyncClient) -> None:
    # There is no single-lead create endpoint (only list/import/delete in
    # leads.py), so the no-cap assertion goes through the CSV import path —
    # the same one that used to call billing_service.check_within_limits
    # before a single lead could be written. One row, far below any old
    # plan's monthly lead cap, proves the path no longer consults billing
    # (it used to 402 without a plan row).
    csv_text = "Email,First Name,Company\ncap-test@example.org,Cap,Acme\n"
    resp = await client.post(
        "/v1/leads/import",
        files={"file": ("leads.csv", csv_text.encode("utf-8"), "text/csv")},
        data={
            "mapping": '{"Email":"email","First Name":"first_name","Company":"company_name"}'
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1
