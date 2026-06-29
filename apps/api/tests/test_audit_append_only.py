"""Audit log: append-only enforcement + hash chain integrity."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from outreach_os.core.db import session_scope

from .conftest import bearer, signup, unique_email


pytestmark = pytest.mark.asyncio


async def test_update_audit_event_is_blocked(client: AsyncClient) -> None:
    pair = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    # Use a single session_scope so the GUC and the destructive statement
    # share one transaction (and therefore one connection from the pool).
    # Doing them in separate sessions would either leak the GUC (`false`)
    # or lose it at commit time (`true`).
    async with session_scope() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": pair["tenant_id"]},
        )
        result = await session.execute(text("SELECT id FROM audit_event LIMIT 1"))
        ev_id = result.scalar()
        assert ev_id is not None, "expected at least one audit row from signup"
        with pytest.raises(Exception) as excinfo:
            await session.execute(
                text("UPDATE audit_event SET action = 'tampered' WHERE id = :id"),
                {"id": str(ev_id)},
            )
        assert "append-only" in str(excinfo.value).lower()


async def test_delete_audit_event_is_blocked(client: AsyncClient) -> None:
    pair = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="Acme",
        tenant_slug="acme",
    )
    async with session_scope() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": pair["tenant_id"]},
        )
        result = await session.execute(text("SELECT id FROM audit_event LIMIT 1"))
        ev_id = result.scalar()
        assert ev_id is not None
        with pytest.raises(Exception) as excinfo:
            await session.execute(
                text("DELETE FROM audit_event WHERE id = :id"), {"id": str(ev_id)}
            )
        assert "append-only" in str(excinfo.value).lower()


async def test_hash_chain_links_within_tenant(client: AsyncClient) -> None:
    """Every row's prev_hash must equal the previous row's row_hash
    (for the same tenant, ordered by created_at)."""
    pair = await signup(
        client,
        email=unique_email(),
        password="correct-horse-battery-staple",
        tenant_name="ChainTest",
        tenant_slug="chain",
    )
    for i in range(3):
        await client.post(
            "/v1/credentials",
            json={
                "kind": "k",
                "label": f"cred-{i}",
                "secret_payload": {"x": i},
            },
            headers=bearer(pair["access_token"]),
        )

    async with session_scope() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"),
            {"t": pair["tenant_id"]},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT id, prev_hash, row_hash FROM audit_event "
                    "WHERE tenant_id = :t ORDER BY created_at ASC, id ASC"
                ),
                {"t": pair["tenant_id"]},
            )
        ).fetchall()

    assert rows[0][1] is None, "first row should have null prev_hash"
    for prev, curr in zip(rows, rows[1:]):
        if prev[2] is not None and curr[1] is not None:
            assert bytes(curr[1]) == bytes(prev[2]), (
                "hash chain broken — tampering or bug detected"
            )
