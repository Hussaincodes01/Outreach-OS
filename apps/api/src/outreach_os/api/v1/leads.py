"""Lead read + delete endpoints."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.core.audit import write_audit_event
from outreach_os.domain.schemas.lead_import import (
    ImportPreviewOut,
    ImportResultOut,
    RowProblemOut,
)
from outreach_os.domain.schemas.lead_scraping import LeadOut, LeadPage
from outreach_os.services import lead_import, lead_service
from outreach_os.services.lead_import import LeadImportError

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=LeadPage)
async def list_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> LeadPage:
    rows = await lead_service.list_leads(
        db,
        tenant_id=user.tenant_id,
        limit=limit,
        offset=offset,
        source=source,
    )
    total = await lead_service.count_leads(db, tenant_id=user.tenant_id)
    return LeadPage(
        items=[LeadOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/import/preview", response_model=ImportPreviewOut)
async def preview_import(
    file: UploadFile = File(..., description="CSV file of leads"),
    user: AuthContext = Depends(get_current_user),
) -> ImportPreviewOut:
    """Read the header row and a few records; suggest a column mapping.

    Nothing is written. The user confirms (or corrects) the mapping before the
    real import, because silently guessing wrong across thousands of rows is
    much more expensive to undo than one extra click.
    """
    content = await file.read()
    try:
        result = lead_import.preview(content)
    except LeadImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ImportPreviewOut(
        headers=result.headers,
        sample_rows=result.sample_rows,
        suggested_mapping=result.suggested_mapping,
        importable_fields=list(lead_import.IMPORTABLE_FIELDS),
        total_rows=result.total_rows,
        truncated=result.truncated,
        max_rows=lead_import.MAX_ROWS,
    )


@router.post("/import", response_model=ImportResultOut)
async def import_leads(
    file: UploadFile = File(..., description="CSV file of leads"),
    mapping: str = Form(..., description='JSON object of {"column": "lead_field"}'),
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> ImportResultOut:
    """Import leads from CSV using a confirmed column mapping.

    Dedupe and the per-row race safety net are reused from the scraping path,
    so an imported list behaves exactly like a scraped one.
    """
    if user.role not in {"owner", "admin", "member"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
        )
    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="mapping must be a JSON object",
        ) from exc
    if not isinstance(mapping_dict, dict) or not mapping_dict:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="mapping must be a non-empty JSON object",
        )

    content = await file.read()
    try:
        parsed = lead_import.parse(content, mapping_dict)
    except LeadImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    inserted, duplicates = await lead_service.insert_leads(
        db, tenant_id=user.tenant_id, job_id=None, raw_leads=parsed.leads
    )

    await write_audit_event(
        db,
        action="lead.imported",
        target_type="tenant",
        target_id=user.tenant_id,
        actor_kind="user",
        actor_id=user.user_id,
        payload={
            "filename": file.filename,
            "imported": inserted,
            "duplicates": duplicates,
            "skipped": parsed.skipped,
            "total_rows": parsed.total_rows,
        },
    )
    return ImportResultOut(
        imported=inserted,
        duplicates=duplicates,
        skipped=parsed.skipped,
        total_rows=parsed.total_rows,
        # Enough to fix the file without returning a megabyte of errors.
        problems=[
            RowProblemOut(row_number=p.row_number, reason=p.reason)
            for p in parsed.problems[:50]
        ],
    )


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    ok = await lead_service.delete_lead(
        db, tenant_id=user.tenant_id, lead_id=lead_id
    )
    if not ok:
        # 404 (not 403) so we don't reveal existence across tenants.
        raise HTTPException(status_code=404, detail="lead not found")
    await write_audit_event(
        db,
        action="lead.deleted",
        target_type="lead",
        target_id=lead_id,
        actor_kind="user",
        actor_id=user.user_id,
    )
