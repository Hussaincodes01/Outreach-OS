"""SuppressionService — manage a tenant's email blocklist."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.domain.models.suppression import Suppression
from outreach_os.domain.schemas.phase4 import SUPPRESSION_REASONS, SuppressionCreateIn


class SuppressionError(RuntimeError):
    pass


class SuppressionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, *, tenant_id: uuid.UUID, data: SuppressionCreateIn
    ) -> Suppression:
        if data.reason not in SUPPRESSION_REASONS:
            raise SuppressionError(f"invalid reason: {data.reason!r}")
        existing = (
            await self.session.execute(
                select(Suppression).where(
                    Suppression.tenant_id == tenant_id,
                    Suppression.email == data.email.lower(),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        row = Suppression(
            tenant_id=tenant_id,
            email=data.email.lower(),
            reason=data.reason,
            source=data.source,
            notes=data.notes,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise SuppressionError(f"already suppressed: {data.email}") from exc
        return row

    async def remove(
        self, *, tenant_id: uuid.UUID, email: str
    ) -> bool:
        row = (
            await self.session.execute(
                select(Suppression).where(
                    Suppression.tenant_id == tenant_id,
                    Suppression.email == email.lower(),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Suppression], int]:
        stmt = select(Suppression).where(Suppression.tenant_id == tenant_id)
        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()
        result = await self.session.execute(
            stmt.order_by(Suppression.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)
