"""Phase 3 — RAG service tests with a deterministic fake LLM.

The RAG service is the only writer of `knowledge_base_chunk` rows. We
verify:
- `add_item` chunks + embeds the text and stores N rows.
- `search` returns relevant chunks with sensible similarity scores.
- `delete_item` cascades to chunks.
- Cross-tenant isolation is preserved.
"""
from __future__ import annotations

import pytest

from outreach_os.core.db import get_session_factory
from outreach_os.core.llm import set_llm_client
from outreach_os.core.tenancy import set_tenant_for_session
from outreach_os.domain.models.tenant import Tenant
from outreach_os.services.rag_service import RAGService
from tests.fake_llm import FakeLLMClient


@pytest.fixture(autouse=True)
def fake_llm():
    """Install the deterministic fake for the duration of each test."""
    fake = FakeLLMClient()
    set_llm_client(fake)
    yield fake
    set_llm_client(None)


async def _ensure_tenant(tenant_id, slug: str, name: str) -> None:
    """Insert a Tenant row directly (no RLS on tenant table) so FK targets
    exist before we set the tenant GUC and write RLS-protected rows."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        existing = await session.get(Tenant, tenant_id)
        if existing is None:
            session.add(
                Tenant(id=tenant_id, slug=slug, name=name, plan="starter", status="active")
            )


async def test_add_item_chunks_and_stores_embeddings():
    """A long body produces multiple chunks; each has an embedding."""
    factory = get_session_factory()
    tenant_id = __import__("uuid").UUID("00000000-0000-0000-0000-0000000000a1")
    await _ensure_tenant(tenant_id, "rag-a1", "Rag A1")
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = RAGService(session)
        body = (
            "Outreach OS helps B2B sales teams scale outbound without losing "
            "personalisation. " * 60  # ~ many chunks
        )
        item = await svc.add_item(
            tenant_id=tenant_id,
            title="B2B outreach case study",
            body=body,
            source="case_studies",
        )
        await session.flush()
        assert item.id is not None
    # The RAG service inserts chunks; verify via a fresh session.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = RAGService(session)
        items = await svc.list_items(tenant_id=tenant_id)
        assert len(items) == 1
        _, count = items[0]
        assert count > 1  # multiple chunks


async def test_search_returns_relevant_chunks():
    factory = get_session_factory()
    tenant_id = __import__("uuid").UUID("00000000-0000-0000-0000-0000000000a2")
    await _ensure_tenant(tenant_id, "rag-a2", "Rag A2")
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = RAGService(session)
        # Two very different bodies.
        await svc.add_item(
            tenant_id=tenant_id,
            title="Sales case study",
            body=(
                "Our team helps B2B SaaS companies 3x their pipeline. "
                "We focus on outbound cold email and LinkedIn at scale."
            ),
        )
        await svc.add_item(
            tenant_id=tenant_id,
            title="Onboarding case study",
            body=(
                "Customer onboarding is the #1 lever for retention. "
                "We rebuilt our activation flow in 6 weeks and saw 40% lift."
            ),
        )

    # Search for "outbound" — should return the sales case study first.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = RAGService(session)
        results = await svc.search(
            tenant_id=tenant_id, query="cold email outbound pipeline"
        )
        assert len(results) >= 1
        # The first hit should be the sales case study (or one of the
        # related chunks). The fake embedding is hash-derived so this
        # is deterministic across runs.
        assert any("outbound" in r.text or "SaaS" in r.text for r in results)
        # All returned similarities must be >= the configured min.
        from outreach_os.core.config import get_settings
        assert all(
            r.similarity >= get_settings().rag_min_similarity for r in results
        )


async def test_search_isolated_per_tenant():
    factory = get_session_factory()
    a = __import__("uuid").UUID("00000000-0000-0000-0000-0000000000a3")
    b = __import__("uuid").UUID("00000000-0000-0000-0000-0000000000a4")
    await _ensure_tenant(a, "rag-a3", "Rag A3")
    await _ensure_tenant(b, "rag-b4", "Rag B4")
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(a))
        svc = RAGService(session)
        await svc.add_item(
            tenant_id=a,
            title="Tenant A confidential",
            body="Tenant A's secret recipe for sales success.",
        )
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(b))
        svc = RAGService(session)
        results = await svc.search(tenant_id=b, query="secret recipe sales")
        # Tenant B sees zero hits.
        assert results == []


async def test_delete_item_cascades_to_chunks():
    factory = get_session_factory()
    tenant_id = __import__("uuid").UUID("00000000-0000-0000-0000-0000000000a5")
    await _ensure_tenant(tenant_id, "rag-a5", "Rag A5")
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = RAGService(session)
        item = await svc.add_item(
            tenant_id=tenant_id,
            title="To delete",
            body=(
                "This case study is about to be removed. " * 20
            ),
        )
        item_id = item.id
        # Now delete (in a fresh transaction so we can verify cascade).
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        svc = RAGService(session)
        ok = await svc.delete_item(tenant_id=tenant_id, item_id=item_id)
        assert ok is True
        # Second call returns False.
        ok2 = await svc.delete_item(tenant_id=tenant_id, item_id=item_id)
        assert ok2 is False
    # Verify chunks are gone.
    async with factory() as session, session.begin():
        await set_tenant_for_session(session, str(tenant_id))
        from sqlalchemy import func, select

        from outreach_os.domain.models.knowledge_base_chunk import (
            KnowledgeBaseChunk,
        )

        count = (
            await session.execute(
                select(func.count(KnowledgeBaseChunk.id)).where(
                    KnowledgeBaseChunk.tenant_id == tenant_id
                )
            )
        ).scalar_one()
        assert count == 0
