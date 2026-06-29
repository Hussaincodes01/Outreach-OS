"""Audit log read + CSV / JSON export."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.models.audit import AuditEvent
from outreach_os.domain.schemas.audit import AuditEventOut, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])


def _to_out(e: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=e.id,
        actor_kind=e.actor_kind,
        actor_id=e.actor_id,
        action=e.action,
        target_type=e.target_type,
        target_id=e.target_id,
        payload=e.payload,
        ip_address=str(e.ip_address) if e.ip_address is not None else None,
        user_agent=e.user_agent,
        created_at=e.created_at,
    )


@router.get("", response_model=AuditPage)
async def list_audit(
    action: str | None = None,
    actor_kind: Annotated[str | None, Query(pattern="^(user|system|agent)$")] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> AuditPage:
    base = select(AuditEvent)
    count_base = select(func.count()).select_from(AuditEvent)
    if action:
        base = base.where(AuditEvent.action == action)
        count_base = count_base.where(AuditEvent.action == action)
    if actor_kind:
        base = base.where(AuditEvent.actor_kind == actor_kind)
        count_base = count_base.where(AuditEvent.actor_kind == actor_kind)
    if from_:
        base = base.where(AuditEvent.created_at >= from_)
        count_base = count_base.where(AuditEvent.created_at >= from_)
    if to:
        base = base.where(AuditEvent.created_at <= to)
        count_base = count_base.where(AuditEvent.created_at <= to)

    total = (await db.execute(count_base)).scalar_one()
    rows = (
        (
            await db.execute(
                base.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return AuditPage(
        items=[_to_out(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export.csv")
async def export_csv(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> StreamingResponse:
    """Stream the current tenant's full audit log as CSV. Memory-bounded
    by streaming in chunks of 500 rows."""
    async def gen() -> AsyncIterator[str]:
        # Async generator on top of a sync CSV writer.
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "created_at",
                "actor_kind",
                "actor_id",
                "action",
                "target_type",
                "target_id",
                "ip_address",
                "user_agent",
                "payload",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        offset = 0
        while True:
            rows = (
                (
                    await db.execute(
                        select(AuditEvent)
                        .order_by(AuditEvent.created_at.asc())
                        .limit(500)
                        .offset(offset)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return
            for r in rows:
                writer.writerow(
                    [
                        str(r.id),
                        r.created_at.isoformat(),
                        r.actor_kind,
                        str(r.actor_id) if r.actor_id else "",
                        r.action,
                        r.target_type or "",
                        str(r.target_id) if r.target_id else "",
                        str(r.ip_address) if r.ip_address else "",
                        r.user_agent or "",
                        (r.payload or {}).get("__repr", str(r.payload)),
                    ]
                )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            offset += 500

    from collections.abc import AsyncIterator

    return StreamingResponse(
        gen(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit.csv"'},
    )


@router.get("/export.json")
async def export_json(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> StreamingResponse:
    """Stream the current tenant's full audit log as JSON lines (NDJSON).

    Memory-bounded by streaming in chunks of 500 rows. One JSON object
    per line; consumers should `split('\n')` and `json.loads` each.
    """

    async def gen() -> "AsyncIterator[bytes]":
        from collections.abc import AsyncIterator

        offset = 0
        while True:
            rows = (
                (
                    await db.execute(
                        select(AuditEvent)
                        .order_by(AuditEvent.created_at.asc())
                        .limit(500)
                        .offset(offset)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return
            for r in rows:
                yield (
                    json.dumps(_to_json_obj(r), separators=(",", ":")).encode("utf-8")
                    + b"\n"
                )
            offset += 500

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="audit.ndjson"'},
    )


def _to_json_obj(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "created_at": e.created_at.isoformat(),
        "actor_kind": e.actor_kind,
        "actor_id": str(e.actor_id) if e.actor_id else None,
        "action": e.action,
        "target_type": e.target_type,
        "target_id": str(e.target_id) if e.target_id else None,
        "ip_address": str(e.ip_address) if e.ip_address is not None else None,
        "user_agent": e.user_agent,
        "payload": e.payload or {},
        "prev_hash": e.prev_hash.hex() if e.prev_hash else None,
        "row_hash": e.row_hash.hex() if e.row_hash else None,
    }
