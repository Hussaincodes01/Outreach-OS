"""CrmClient abstraction \u2014 provider-agnostic write-side for CRM sync.

V1 supports Google Sheets only. The default in dev / tests is
`StubCrmClient` which records every `append_row` call in-memory so
the e2e demo can assert what was written.

`CrmClient` is intentionally write-side only for V1 (the master plan
says "status updates flow both ways" \u2014 we add the read/poll side in
Phase 6 if needed). Each adapter knows how to:
  - mint/refresh an access token from the connection's credential
  - serialise the meeting + lead into a row dict per the connection's
    column_mapping
  - append the row to the remote spreadsheet/CRM
  - return a stable `external_id` (e.g. spreadsheet row number) so we
    can show it in the UI.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)


class CrmError(RuntimeError):
    pass


@dataclass
class CrmRow:
    """A row to write to a CRM. Maps 1:1 to one spreadsheet row or
    one CRM record. Field names are the Outreach OS field names
    (first_name, email, company_name, etc.) \u2014 the adapter translates
    to the right columns."""
    fields: dict[str, Any] = field(default_factory=dict)
    external_id: str | None = None
    raw: dict[str, Any] | None = None


class CrmClient(Protocol):
    def append_row(self, *, spreadsheet_id: str, sheet_range: str,
                   column_mapping: dict[str, str], row: CrmRow,
                   access_token: str) -> CrmRow: ...


class StubCrmClient:
    """Default CRM client for dev / tests.

    Translates `CrmRow.fields` to an ordered list using the
    `column_mapping` (e.g. {"first_name": "A", "email": "B"} \u2192
    fields are placed in column order). Records everything in `self.rows`.
    """

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.should_fail = False

    def append_row(
        self,
        *,
        spreadsheet_id: str,
        sheet_range: str,
        column_mapping: dict[str, str],
        row: CrmRow,
        access_token: str,
    ) -> CrmRow:
        if self.should_fail:
            raise CrmError("stub crm configured to fail")
        # Order the fields per column letter.
        ordered = sorted(
            column_mapping.items(),
            key=lambda kv: kv[1],
        )
        values = [str(row.fields.get(outreach_field, "")) for
                  outreach_field, _ in ordered]
        external_id = f"row-stub-{secrets.token_hex(4)}"
        record = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_range": sheet_range,
            "values": values,
            "column_mapping": dict(column_mapping),
            "input_fields": dict(row.fields),
            "external_id": external_id,
        }
        self.rows.append(record)
        log.info("stub-crm append spreadsheet=%s range=%s values=%s",
                 spreadsheet_id, sheet_range, values)
        return CrmRow(fields=dict(row.fields),
                      external_id=external_id,
                      raw={"stub": True, "row": record})

    def reset(self) -> None:
        self.rows = []
        self.should_fail = False


# --- Module-level singleton ---

_default_crm: CrmClient | None = None


def get_crm_client() -> CrmClient:
    global _default_crm
    if _default_crm is None:
        _default_crm = StubCrmClient()
    return _default_crm


def set_crm_client(client: CrmClient | None) -> None:
    global _default_crm
    _default_crm = client


__all__ = [
    "CrmClient",
    "CrmError",
    "CrmRow",
    "StubCrmClient",
    "get_crm_client",
    "set_crm_client",
]
