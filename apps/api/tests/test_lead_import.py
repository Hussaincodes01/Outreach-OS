"""CSV lead import.

This is the path a brand-new customer takes on day one: they arrive with a list
they already own. Before this existed, leads could only come from the scraping
pipeline, which needs a paid Serper or Proxycurl key — so the product was
unusable until they bought something else first.
"""
from __future__ import annotations

import pytest

from outreach_os.services import lead_import
from outreach_os.services.lead_import import LeadImportError
from tests.conftest import bearer, signup, unique_email

pytestmark = pytest.mark.asyncio

_CSV = (
    "First Name,Last Name,Email,Company,Job Title,Website\n"
    "Sam,Carter,sam@northwind.example,Northwind Labs,VP Sales,https://www.northwind.example/about\n"
    "Jo,Patel,jo@brightpath.example,Brightpath,Head of Sales,brightpath.example\n"
)


def _upload(csv_text: str, name: str = "leads.csv") -> dict:
    return {"file": (name, csv_text.encode("utf-8"), "text/csv")}


# --- parsing ----------------------------------------------------------------


async def test_headers_are_matched_across_common_export_formats() -> None:
    """Real exports spell these differently; a user should not have to map
    every column by hand."""
    mapping = lead_import.suggest_mapping(
        ["First Name", "Last Name", "Email Address", "Company", "Job Title", "Website"]
    )
    assert mapping["First Name"] == "first_name"
    assert mapping["Last Name"] == "last_name"
    assert mapping["Email Address"] == "email"
    assert mapping["Company"] == "company_name"
    assert mapping["Job Title"] == "title"
    assert mapping["Website"] == "domain"


async def test_a_field_is_never_claimed_twice() -> None:
    """Two email-ish columns must not both map to `email`."""
    mapping = lead_import.suggest_mapping(["Email", "Work Email"])
    assert list(mapping.values()).count("email") == 1


async def test_excel_byte_order_mark_does_not_break_the_first_column() -> None:
    """Excel writes a BOM; without stripping it the first header silently
    fails to map and the user cannot see why."""
    content = ("﻿" + _CSV).encode("utf-8")
    preview = lead_import.preview(content)
    assert preview.headers[0] == "First Name"
    assert preview.suggested_mapping["First Name"] == "first_name"


async def test_semicolon_delimited_files_are_handled() -> None:
    """European Excel exports use semicolons."""
    csv_text = "Email;Company\nsam@x.example;Acme\n"
    preview = lead_import.preview(csv_text.encode("utf-8"))
    assert preview.headers == ["Email", "Company"]
    assert preview.total_rows == 1


async def test_urls_are_reduced_to_bare_domains() -> None:
    parsed = lead_import.parse(_CSV.encode("utf-8"), {"Email": "email", "Website": "domain"})
    assert [lead.domain for lead in parsed.leads] == [
        "northwind.example",
        "brightpath.example",
    ]


async def test_unmapped_columns_are_kept_for_personalisation() -> None:
    """The column a user didn't map is often the one that makes an email
    personal, so it is preserved rather than discarded."""
    csv_text = "Email,Recent Funding\nsam@x.example,Series A led by Acme\n"
    parsed = lead_import.parse(csv_text.encode("utf-8"), {"Email": "email"})
    assert parsed.leads[0].raw_data["Recent Funding"] == "Series A led by Acme"


async def test_invalid_rows_are_reported_with_line_numbers_not_dropped() -> None:
    csv_text = (
        "Email,Company\n"
        "good@x.example,Acme\n"
        "not-an-email,Broken Co\n"
        ",No Contact\n"
        "good@x.example,Duplicate\n"
    )
    parsed = lead_import.parse(csv_text.encode("utf-8"), {"Email": "email"})
    assert len(parsed.leads) == 1
    reasons = {p.row_number: p.reason for p in parsed.problems}
    assert "Invalid email" in reasons[3]
    assert "No email or domain" in reasons[4]
    assert "Duplicate" in reasons[5]


async def test_mapping_without_email_or_domain_is_refused() -> None:
    """A lead with neither can be neither contacted nor enriched."""
    with pytest.raises(LeadImportError, match=r"email.*or.*domain"):
        lead_import.parse(_CSV.encode("utf-8"), {"Company": "company_name"})


async def test_unknown_target_field_is_refused() -> None:
    with pytest.raises(LeadImportError, match="Unknown field"):
        lead_import.parse(_CSV.encode("utf-8"), {"Email": "email", "Company": "salary"})


async def test_empty_and_headerless_files_give_readable_errors() -> None:
    with pytest.raises(LeadImportError, match="empty"):
        lead_import.preview(b"   ")


async def test_row_limit_is_enforced() -> None:
    """A whole-CRM export must produce a clear message, not a dead worker."""
    rows = "\n".join(f"user{i}@x.example" for i in range(lead_import.MAX_ROWS + 10))
    parsed = lead_import.parse(f"Email\n{rows}\n".encode(), {"Email": "email"})
    assert len(parsed.leads) == lead_import.MAX_ROWS
    assert any("import limit" in p.reason for p in parsed.problems)


# --- API --------------------------------------------------------------------


async def test_preview_suggests_a_mapping_without_writing_anything(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Preview Co",
    )
    headers = bearer(a["access_token"])
    resp = await client.post(
        "/v1/leads/import/preview", files=_upload(_CSV), headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 2
    assert body["suggested_mapping"]["Email"] == "email"
    assert "email" in body["importable_fields"]
    assert len(body["sample_rows"]) == 2

    # Preview must not create anything.
    leads = (await client.get("/v1/leads", headers=headers)).json()
    assert leads["total"] == 0


async def test_import_creates_leads(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Import Co",
    )
    headers = bearer(a["access_token"])
    resp = await client.post(
        "/v1/leads/import",
        files=_upload(_CSV),
        data={"mapping": '{"Email":"email","First Name":"first_name","Company":"company_name"}'},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["duplicates"] == 0

    leads = (await client.get("/v1/leads", headers=headers)).json()
    assert leads["total"] == 2
    by_email = {item["email"]: item for item in leads["items"]}
    assert by_email["sam@northwind.example"]["first_name"] == "Sam"
    assert by_email["sam@northwind.example"]["company_name"] == "Northwind Labs"
    assert by_email["sam@northwind.example"]["source"] == lead_import.IMPORT_SOURCE


async def test_reimporting_the_same_file_creates_no_duplicates(client) -> None:
    """Customers re-upload an updated export constantly."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Dedupe Co",
    )
    headers = bearer(a["access_token"])
    payload = {"mapping": '{"Email":"email"}'}
    first = await client.post(
        "/v1/leads/import", files=_upload(_CSV), data=payload, headers=headers
    )
    second = await client.post(
        "/v1/leads/import", files=_upload(_CSV), data=payload, headers=headers
    )
    assert first.json()["imported"] == 2
    assert second.json()["imported"] == 0
    assert second.json()["duplicates"] == 2
    assert (await client.get("/v1/leads", headers=headers)).json()["total"] == 2


async def test_import_is_tenant_isolated(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Tenant A",
    )
    b = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Tenant B",
    )
    await client.post(
        "/v1/leads/import",
        files=_upload(_CSV),
        data={"mapping": '{"Email":"email"}'},
        headers=bearer(a["access_token"]),
    )
    assert (await client.get("/v1/leads", headers=bearer(b["access_token"]))).json()["total"] == 0
    # Both tenants can hold the same address without colliding.
    resp = await client.post(
        "/v1/leads/import",
        files=_upload(_CSV),
        data={"mapping": '{"Email":"email"}'},
        headers=bearer(b["access_token"]),
    )
    assert resp.json()["imported"] == 2


async def test_bad_mapping_json_is_rejected(client) -> None:
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="BadMap",
    )
    resp = await client.post(
        "/v1/leads/import",
        files=_upload(_CSV),
        data={"mapping": "not json"},
        headers=bearer(a["access_token"]),
    )
    assert resp.status_code == 422


async def test_import_completes_the_onboarding_step(client) -> None:
    """The checklist promised "import a list"; it must now be satisfiable."""
    a = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Onboard Co",
    )
    headers = bearer(a["access_token"])
    before = (await client.get("/v1/onboarding", headers=headers)).json()
    leads_step = next(s for s in before["steps"] if s["key"] == "leads")
    assert leads_step["done"] is False

    await client.post(
        "/v1/leads/import",
        files=_upload(_CSV),
        data={"mapping": '{"Email":"email"}'},
        headers=headers,
    )
    after = (await client.get("/v1/onboarding", headers=headers)).json()
    leads_step = next(s for s in after["steps"] if s["key"] == "leads")
    assert leads_step["done"] is True
