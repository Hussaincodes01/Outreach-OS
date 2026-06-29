"""Append-only audit log writer.

Every state-changing endpoint should call write_audit_event. The table
itself is locked down by a Postgres trigger that raises on UPDATE/DELETE.

We compute row_hash = SHA256( serialised_row || prev_hash ) so tampering
with one row invalidates the chain from that point forward.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.tenancy import get_current_tenant_id


def _serialise_event(
    *,
    id_: uuid.UUID,
    tenant_id: uuid.UUID,
    actor_kind: str,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None,
    target_id: uuid.UUID | None,
    payload: dict[str, Any],
    ip_address: str | None,
    user_agent: str | None,
    created_at: datetime,
    prev_hash: bytes | None,
) -> bytes:
    obj = {
        "id": str(id_),
        "tenant_id": str(tenant_id),
        "actor_kind": actor_kind,
        "actor_id": str(actor_id) if actor_id else None,
        "action": action,
        "target_type": target_type,
        "target_id": str(target_id) if target_id else None,
        "payload": payload,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "created_at": created_at.isoformat(),
    }
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if prev_hash:
        return raw + b"|" + prev_hash
    return raw


def _hash_event(serialised: bytes) -> bytes:
    return hashlib.sha256(serialised).digest()


async def _latest_hash_for_tenant(
    session: AsyncSession, tenant_id: uuid.UUID
) -> bytes | None:
    result = await session.execute(
        text(
            "SELECT row_hash FROM audit_event "
            "WHERE tenant_id = :tid "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ),
        {"tid": str(tenant_id)},
    )
    row = result.first()
    return row[0] if row else None


async def write_audit_event(
    session: AsyncSession,
    *,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    actor_kind: str = "system",
    actor_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    tenant_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Append a single audit event in the current tenant's chain.

    `tenant_id` is normally inferred from the request context (set by
    the auth dependency). Pass it explicitly for background work.
    """
    effective_tenant = tenant_id or (
        uuid.UUID(get_current_tenant_id()) if get_current_tenant_id() else None
    )
    if effective_tenant is None:
        raise RuntimeError("audit_event requires a tenant_id (context or arg)")

    event_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    safe_payload = payload or {}

    prev_hash = await _latest_hash_for_tenant(session, effective_tenant)
    serialised = _serialise_event(
        id_=event_id,
        tenant_id=effective_tenant,
        actor_kind=actor_kind,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=safe_payload,
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=created_at,
        prev_hash=prev_hash,
    )
    row_hash = _hash_event(serialised)

    # We bypass ORM here because the audit_event model lives in domain.models
    # but we want the row insert to be tight + under RLS (tenant_id must match
    # the current_setting). Direct SQL keeps it obvious.
    await session.execute(
        text(
            """
            INSERT INTO audit_event (
                id, tenant_id, actor_kind, actor_id, action,
                target_type, target_id, payload, ip_address, user_agent,
                created_at, prev_hash, row_hash
            ) VALUES (
                :id, :tid, :ak, :aid, :act,
                :tt, :tid_target, :payload, :ip, :ua,
                :ts, :ph, :rh
            )
            """
        ),
        {
            "id": str(event_id),
            "tid": str(effective_tenant),
            "ak": actor_kind,
            "aid": str(actor_id) if actor_id else None,
            "act": action,
            "tt": target_type,
            "tid_target": str(target_id) if target_id else None,
            "payload": json.dumps(safe_payload),
            "ip": ip_address,
            "ua": user_agent,
            "ts": created_at,
            "ph": prev_hash,
            "rh": row_hash,
        },
    )
    return event_id


__all__ = ["write_audit_event"]
