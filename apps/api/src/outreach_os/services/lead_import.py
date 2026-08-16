"""Import leads from a customer's own CSV.

Until now leads could only arrive via the scraping pipeline, which needs a paid
Serper or Proxycurl key. That made the product unusable on day one for anyone
arriving with a list they already own — the common case.

The flow is two-step by design:

1. `preview()` reads the header row and a handful of records, guesses which
   column means what, and hands that back so the user can correct it. Guessing
   silently and importing thousands of rows into the wrong fields is far worse
   than one extra click.
2. `parse()` applies the confirmed mapping and returns clean `RawLead`s plus
   per-row problems, so a bad file can be fixed rather than half-imported.

Parsing lives on the server: Python's `csv` module already handles quoting,
embedded newlines and BOMs correctly, and doing it here means the endpoint is
equally usable from a script.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from outreach_os.services.scraping.raw_lead import RawLead

# The `source` value recorded against imported leads. Distinct from the
# scraping sources so imported rows stay identifiable in the audit trail.
IMPORT_SOURCE = "csv_import"

# Ceilings. A customer pasting an export of their whole CRM should get a clear
# message, not a timeout or an out-of-memory worker.
MAX_ROWS = 5_000
MAX_BYTES = 10_000_000
PREVIEW_ROWS = 5

# Fields a column can be mapped onto. Mirrors the subset of Lead worth setting
# from a spreadsheet; everything else on the row is preserved in raw_data.
IMPORTABLE_FIELDS: tuple[str, ...] = (
    "email",
    "first_name",
    "last_name",
    "full_name",
    "company_name",
    "title",
    "domain",
    "linkedin_url",
    "country",
    "industry",
    "company_size",
)

# Header spellings seen in real exports (Apollo, Sales Navigator, HubSpot,
# Clay, plain spreadsheets). Matching is case- and punctuation-insensitive.
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "email": ("email", "emailaddress", "workemail", "businessemail", "mail", "primaryemail"),
    "first_name": ("firstname", "first", "givenname", "forename"),
    "last_name": ("lastname", "last", "surname", "familyname"),
    "full_name": ("fullname", "name", "contactname", "person", "leadname"),
    "company_name": ("company", "companyname", "organisation", "organization", "account", "employer"),
    "title": ("title", "jobtitle", "position", "role", "headline"),
    "domain": ("domain", "website", "companydomain", "companywebsite", "url", "site"),
    "linkedin_url": ("linkedin", "linkedinurl", "linkedinprofile", "profileurl"),
    "country": ("country", "countryregion", "location", "region"),
    "industry": ("industry", "sector", "vertical"),
    "company_size": ("companysize", "employees", "headcount", "employeecount", "size"),
}

# Deliberately permissive: rejecting a deliverable address because it has an
# apostrophe or a long TLD loses the customer real leads. The provider is the
# real authority on deliverability.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

_NON_ALNUM = re.compile(r"[^a-z0-9]")


class LeadImportError(ValueError):
    """The file could not be read at all (not a per-row problem)."""


@dataclass
class RowProblem:
    """One row we could not import, and why — reported back with its line
    number so the customer can fix the file rather than guess."""

    row_number: int
    reason: str


@dataclass
class ParsedImport:
    leads: list[RawLead] = field(default_factory=list)
    problems: list[RowProblem] = field(default_factory=list)
    total_rows: int = 0

    @property
    def skipped(self) -> int:
        return len(self.problems)


@dataclass
class ImportPreview:
    headers: list[str]
    sample_rows: list[dict[str, str]]
    suggested_mapping: dict[str, str]
    total_rows: int
    truncated: bool


def _normalise(header: str) -> str:
    return _NON_ALNUM.sub("", header.strip().lower())


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    """Best-effort column -> field guess, for the user to confirm.

    Each field is claimed at most once; the leftmost matching column wins, so
    a file with both "Email" and "Personal Email" maps the first.
    """
    mapping: dict[str, str] = {}
    claimed: set[str] = set()
    for header in headers:
        key = _normalise(header)
        if not key:
            continue
        for field_name, aliases in _HEADER_ALIASES.items():
            if field_name in claimed:
                continue
            if key == field_name or key in aliases:
                mapping[header] = field_name
                claimed.add(field_name)
                break
    return mapping


def _read_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if len(content) > MAX_BYTES:
        raise LeadImportError(
            f"File is larger than {MAX_BYTES // 1_000_000}MB. Split it and import in parts."
        )
    if not content.strip():
        raise LeadImportError("The file is empty.")

    # utf-8-sig strips the BOM Excel writes, which would otherwise corrupt the
    # first header and make its mapping fail for no visible reason.
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise LeadImportError("Could not decode the file as text.") from exc

    sample = text[:8192]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # Sensible default for a single-column file.

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise LeadImportError("Could not find a header row.")

    headers = [h.strip() for h in reader.fieldnames if h and h.strip()]
    if not headers:
        raise LeadImportError("The header row is blank.")

    rows: list[dict[str, str]] = []
    for raw_row in reader:
        rows.append(
            {
                (k or "").strip(): (v or "").strip()
                for k, v in raw_row.items()
                if k is not None
            }
        )
    return headers, rows


def preview(content: bytes) -> ImportPreview:
    """Headers, a few example rows, and a suggested mapping to confirm."""
    headers, rows = _read_csv(content)
    return ImportPreview(
        headers=headers,
        sample_rows=rows[:PREVIEW_ROWS],
        suggested_mapping=suggest_mapping(headers),
        total_rows=len(rows),
        truncated=len(rows) > MAX_ROWS,
    )


def _clean_domain(value: str) -> str:
    """Accept whatever the spreadsheet holds — a bare domain or a full URL."""
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.split("/")[0].strip()


def parse(content: bytes, mapping: dict[str, str]) -> ParsedImport:
    """Apply a confirmed mapping and return importable leads plus problems.

    Rows are validated but never silently dropped: anything unusable comes back
    in `problems` with its line number.
    """
    _, rows = _read_csv(content)

    unknown = sorted(set(mapping.values()) - set(IMPORTABLE_FIELDS))
    if unknown:
        raise LeadImportError(f"Unknown field(s) in mapping: {', '.join(unknown)}")
    if not any(f in ("email", "domain") for f in mapping.values()):
        raise LeadImportError(
            "Map a column to either 'email' or 'domain' — without one of them a "
            "lead cannot be contacted or enriched."
        )

    result = ParsedImport(total_rows=len(rows))
    seen_emails: set[str] = set()

    for index, row in enumerate(rows):
        # +2: one for the header line, one because humans count from 1.
        line_no = index + 2
        if len(result.leads) >= MAX_ROWS:
            result.problems.append(
                RowProblem(line_no, f"Skipped — over the {MAX_ROWS}-row import limit")
            )
            continue

        values: dict[str, str] = {}
        for column, field_name in mapping.items():
            raw = (row.get(column) or "").strip()
            if raw:
                values[field_name] = raw

        email = values.get("email", "").lower()
        if email and not _EMAIL_RE.match(email):
            result.problems.append(RowProblem(line_no, f"Invalid email: {email!r}"))
            continue

        domain = _clean_domain(values.get("domain", ""))
        if not email and not domain:
            result.problems.append(RowProblem(line_no, "No email or domain"))
            continue

        if email:
            if email in seen_emails:
                result.problems.append(
                    RowProblem(line_no, f"Duplicate of an earlier row: {email}")
                )
                continue
            seen_emails.add(email)

        # Columns the user did not map are still worth keeping: they often hold
        # the detail that makes an email personal.
        mapped_columns = set(mapping)
        extras = {
            k: v for k, v in row.items() if k not in mapped_columns and v
        }

        result.leads.append(
            RawLead(
                source=IMPORT_SOURCE,
                email=email or None,
                domain=domain or None,
                first_name=values.get("first_name"),
                last_name=values.get("last_name"),
                full_name=values.get("full_name"),
                company_name=values.get("company_name"),
                title=values.get("title"),
                linkedin_url=values.get("linkedin_url"),
                country=values.get("country"),
                industry=values.get("industry"),
                company_size=values.get("company_size"),
                raw_data={"import_row": line_no, **extras} if extras else {"import_row": line_no},
            )
        )

    return result


__all__ = [
    "IMPORTABLE_FIELDS",
    "IMPORT_SOURCE",
    "MAX_BYTES",
    "MAX_ROWS",
    "ImportPreview",
    "LeadImportError",
    "ParsedImport",
    "RowProblem",
    "parse",
    "preview",
    "suggest_mapping",
]
