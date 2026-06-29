"""In-memory per-tenant WebSocket connection registry.

Why in-memory? Phase 6 is a single-pod app. When we move to
multi-pod deployment in Phase 8 hardening we'll swap this for Redis
pub/sub; the interface stays the same.

The registry is keyed by `tenant_id`. Each tenant can have N
subscribers (one per browser tab the user has open). When a new
notification fires, `broadcast(tenant_id, event)` iterates and
calls `send_text` on each socket. Closed sockets are evicted on
the fly.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class TenantConnectionManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections: dict[UUID, set[WebSocket]] = {}

    async def connect(self, tenant_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(tenant_id, set()).add(websocket)
        logger.info("ws: tenant=%s connected, total=%d", tenant_id,
                    len(self._connections[tenant_id]))

    async def disconnect(self, tenant_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(tenant_id)
            if conns and websocket in conns:
                conns.discard(websocket)
                if not conns:
                    self._connections.pop(tenant_id, None)
        logger.info("ws: tenant=%s disconnected", tenant_id)

    async def broadcast(self, tenant_id: UUID, event: dict[str, Any]) -> None:
        async with self._lock:
            conns = list(self._connections.get(tenant_id, ()))
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(event)
            except Exception as e:
                logger.warning("ws: send failed: %s", e)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    conns2 = self._connections.get(tenant_id)
                    if conns2:
                        conns2.discard(ws)
                        if not conns2:
                            self._connections.pop(tenant_id, None)

    def active_tenants(self) -> int:
        return len(self._connections)

    def total_connections(self) -> int:
        return sum(len(c) for c in self._connections.values())


_manager: TenantConnectionManager | None = None


def get_ws_manager() -> TenantConnectionManager:
    global _manager
    if _manager is None:
        _manager = TenantConnectionManager()
    return _manager


def set_ws_manager(m: TenantConnectionManager | None) -> None:
    """Test seam \u2014 reset to a fresh manager."""
    global _manager
    _manager = m


__all__ = [
    "TenantConnectionManager",
    "get_ws_manager",
    "set_ws_manager",
]
