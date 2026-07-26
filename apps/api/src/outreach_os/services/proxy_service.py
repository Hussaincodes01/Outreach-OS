"""Per-tenant proxy config service.

Proxies are optional. When the tenant has at least one active proxy,
the scraping service will rotate through them; the rotation policy
lives in the worker (round-robin for now). The encrypted blob stores
the full URL (with optional user:pass) so the worker can build a
complete `proxies={"https://": url}` dict for httpx.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.errors import ConflictError, ValidationError
from outreach_os.domain.models.proxy import Proxy
from outreach_os.services import vault_service


async def list_proxies(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Proxy]:
    result = await session.execute(
        select(Proxy).where(Proxy.tenant_id == tenant_id).order_by(Proxy.created_at.desc())
    )
    return list(result.scalars().all())


async def create_proxy(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    label: str,
    protocol: str,
    host: str,
    port: int,
    url: str | None,
) -> Proxy:
    if protocol not in {"http", "https", "socks5"}:
        raise ValidationError(f"invalid protocol: {protocol}")
    if not (1 <= port <= 65535):
        raise ValidationError("port must be in [1, 65535]")

    ciphertext: bytes | None = None
    if url:
        ciphertext = vault_service.encrypt_for_tenant(str(tenant_id), {"url": url})

    row = Proxy(
        tenant_id=tenant_id,
        label=label,
        protocol=protocol,
        host=host,
        port=port,
        url_ciphertext=ciphertext,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"proxy with label {label!r} already exists for this tenant") from exc
    return row


async def delete_proxy(
    session: AsyncSession, *, tenant_id: uuid.UUID, proxy_id: uuid.UUID
) -> bool:
    row = await session.get(Proxy, proxy_id)
    if row is None or row.tenant_id != tenant_id:
        return False
    await session.delete(row)
    await session.flush()
    return True


def decrypt_url(tenant_id: str, ciphertext: bytes | None) -> str | None:
    if ciphertext is None:
        return None
    data: dict[str, Any] = vault_service.decrypt_for_tenant(tenant_id, ciphertext)
    return data.get("url")


__all__ = [
    "create_proxy",
    "decrypt_url",
    "delete_proxy",
    "list_proxies",
]
