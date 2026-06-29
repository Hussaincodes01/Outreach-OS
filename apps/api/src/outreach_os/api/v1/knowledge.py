"""Phase 3 — knowledge base endpoints (case studies / past wins)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.schemas.phase3 import (
    KnowledgeBaseItemCreate,
    KnowledgeBaseItemOut,
    KnowledgeBaseItemPage,
    KnowledgeBaseItemSummary,
)
from outreach_os.services.rag_service import RAGService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=KnowledgeBaseItemPage)
async def list_items(
    limit: int = 50,
    offset: int = 0,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> KnowledgeBaseItemPage:
    svc = RAGService(db)
    total = await svc.count_items(tenant_id=user.tenant_id)
    items_with_counts = await svc.list_items(
        tenant_id=user.tenant_id, limit=limit, offset=offset
    )
    summaries: list[KnowledgeBaseItemSummary] = []
    for item, count in items_with_counts:
        summaries.append(
            KnowledgeBaseItemSummary(
                id=item.id,
                created_at=item.created_at,
                tenant_id=item.tenant_id,
                title=item.title,
                source=item.source,
                chunk_count=count,
            )
        )
    return KnowledgeBaseItemPage(items=summaries, total=total, limit=limit, offset=offset)


@router.post(
    "", response_model=KnowledgeBaseItemOut, status_code=status.HTTP_201_CREATED
)
async def add_item(
    data: KnowledgeBaseItemCreate,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> KnowledgeBaseItemOut:
    svc = RAGService(db)
    item = await svc.add_item(
        tenant_id=user.tenant_id, title=data.title, body=data.body, source=data.source
    )
    await db.flush()
    chunk_count = await svc.count_items_chunks(item_id=item.id)
    return KnowledgeBaseItemOut(
        id=item.id,
        created_at=item.created_at,
        tenant_id=item.tenant_id,
        title=item.title,
        source=item.source,
        body=item.body,
        chunk_count=chunk_count,
    )


@router.get("/{item_id}", response_model=KnowledgeBaseItemOut)
async def get_item(
    item_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> KnowledgeBaseItemOut:
    svc = RAGService(db)
    items = await svc.list_items(tenant_id=user.tenant_id, limit=1, offset=0)
    for item, count in items:
        if item.id == item_id:
            return KnowledgeBaseItemOut(
                id=item.id,
                created_at=item.created_at,
                tenant_id=item.tenant_id,
                title=item.title,
                source=item.source,
                body=item.body,
                chunk_count=count,
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge item not found")


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> None:
    svc = RAGService(db)
    ok = await svc.delete_item(tenant_id=user.tenant_id, item_id=item_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge item not found")
