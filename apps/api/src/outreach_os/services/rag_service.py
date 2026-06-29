"""RAG service — chunk text, embed via LiteLLM, retrieve by cosine similarity.

Pipeline:
1. On `add_item(title, body)` we tokenize the body with tiktoken, split
   it into ~400-token windows with ~60-token overlap, embed each chunk
   via the configured embedding model, and INSERT the chunks.
2. On `search(query, k)` we embed the query, run a pgvector cosine
   similarity search, and return the top-k chunks above the minimum
   similarity threshold.

The RAG service is the only writer of `knowledge_base_chunk` rows. It
runs in the request's async session so RLS scopes the search to the
current tenant.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable

import tiktoken
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.llm import LLMClient, get_llm_client
from outreach_os.domain.models.knowledge_base_chunk import (
    EMBEDDING_DIM,
    KnowledgeBaseChunk,
)
from outreach_os.domain.models.knowledge_base_item import KnowledgeBaseItem


# --- Tokenizer --------------------------------------------------------------

# cl100k_base is the tokenizer used by text-embedding-3-* and gpt-4*. Good
# enough for English business text. If we ever switch to a model with a
# different vocabulary, swap this constant.
_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text_str: str) -> int:
    return len(_ENCODING.encode(text_str))


def _encode_chunks(
    text_str: str, *, chunk_tokens: int, overlap_tokens: int
) -> list[str]:
    """Sliding-window chunker. We split on token boundaries, then decode
    the tokens back to text. This guarantees chunks align with the model's
    BPE, even at chunk boundaries."""
    if not text_str.strip():
        return []
    tokens = _ENCODING.encode(text_str)
    if len(tokens) <= chunk_tokens:
        return [text_str]
    step = max(1, chunk_tokens - overlap_tokens)
    chunks: list[str] = []
    for start in range(0, len(tokens), step):
        end = min(len(tokens), start + chunk_tokens)
        chunk_tokens_slice = tokens[start:end]
        if not chunk_tokens_slice:
            break
        chunk_text = _ENCODING.decode(chunk_tokens_slice)
        chunks.append(chunk_text)
        if end == len(tokens):
            break
    return chunks


# --- Data classes -----------------------------------------------------------


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    item_id: uuid.UUID
    item_title: str
    text: str
    # Cosine similarity in [0, 1]. pgvector returns cosine *distance* (lower
    # is closer); we convert here so callers can use a simple threshold.
    similarity: float


# --- Service ----------------------------------------------------------------


class RAGService:
    def __init__(self, session: AsyncSession, *, llm: LLMClient | None = None) -> None:
        self.session = session
        self.llm = llm or get_llm_client()
        self.settings = get_settings()

    # --- Writes ---

    async def add_item(
        self, *, tenant_id: uuid.UUID, title: str, body: str, source: str | None = None
    ) -> KnowledgeBaseItem:
        """Insert the raw item, chunk + embed + insert chunks. Idempotent
        on (item_id, chunk_index) thanks to the unique index."""
        item = KnowledgeBaseItem(
            tenant_id=tenant_id, title=title, source=source, body=body
        )
        self.session.add(item)
        await self.session.flush()  # populate item.id

        chunks = _encode_chunks(
            body,
            chunk_tokens=self.settings.rag_chunk_tokens,
            overlap_tokens=self.settings.rag_chunk_overlap_tokens,
        )
        if chunks:
            embeddings = self.llm.embed(
                self.settings.llm_embedding_model, chunks
            )
            for idx, (text_chunk, vec) in enumerate(zip(chunks, embeddings, strict=True)):
                if len(vec) != EMBEDDING_DIM:
                    raise ValueError(
                        f"embedding dim mismatch: got {len(vec)}, expected {EMBEDDING_DIM}"
                    )
                self.session.add(
                    KnowledgeBaseChunk(
                        tenant_id=tenant_id,
                        item_id=item.id,
                        chunk_index=idx,
                        text=text_chunk,
                        embedding=vec,
                        token_count=_count_tokens(text_chunk),
                    )
                )
        return item

    async def delete_item(self, *, tenant_id: uuid.UUID, item_id: uuid.UUID) -> bool:
        """Delete an item (cascades to chunks). Returns True if a row was removed."""
        result = await self.session.execute(
            delete(KnowledgeBaseItem)
            .where(KnowledgeBaseItem.tenant_id == tenant_id)
            .where(KnowledgeBaseItem.id == item_id)
        )
        return (result.rowcount or 0) > 0

    # --- Reads ---

    async def count_items(self, *, tenant_id: uuid.UUID) -> int:
        from sqlalchemy import func

        result = await self.session.execute(
            select(func.count(KnowledgeBaseItem.id)).where(
                KnowledgeBaseItem.tenant_id == tenant_id
            )
        )
        return int(result.scalar_one() or 0)

    async def count_items_chunks(self, *, item_id: uuid.UUID) -> int:
        """How many chunks does a single item have? Useful right after
        `add_item` when we want to return the chunk count in the response."""
        from sqlalchemy import func

        result = await self.session.execute(
            select(func.count(KnowledgeBaseChunk.id)).where(
                KnowledgeBaseChunk.item_id == item_id
            )
        )
        return int(result.scalar_one() or 0)

    async def list_items(
        self, *, tenant_id: uuid.UUID, limit: int = 50, offset: int = 0
    ) -> list[tuple[KnowledgeBaseItem, int]]:
        """Return (item, chunk_count) tuples, newest first."""
        # Two-step: items + counts. Good enough at this scale.
        from sqlalchemy import func

        items_result = await self.session.execute(
            select(KnowledgeBaseItem)
            .where(KnowledgeBaseItem.tenant_id == tenant_id)
            .order_by(KnowledgeBaseItem.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list(items_result.scalars().all())
        if not items:
            return []
        ids = [i.id for i in items]
        counts_result = await self.session.execute(
            select(
                KnowledgeBaseChunk.item_id,
                func.count(KnowledgeBaseChunk.id),
            )
            .where(KnowledgeBaseChunk.tenant_id == tenant_id)
            .where(KnowledgeBaseChunk.item_id.in_(ids))
            .group_by(KnowledgeBaseChunk.item_id)
        )
        counts = {row[0]: int(row[1]) for row in counts_result.all()}
        return [(i, counts.get(i.id, 0)) for i in items]

    async def search(
        self,
        *,
        tenant_id: uuid.UUID,
        query: str,
        k: int | None = None,
        min_similarity: float | None = None,
    ) -> list[RetrievedChunk]:
        """Embed `query` and return the top-k chunks for the current tenant
        whose cosine similarity is at least `min_similarity`."""
        k = k or self.settings.rag_top_k
        min_sim = min_similarity if min_similarity is not None else self.settings.rag_min_similarity

        if not query.strip():
            return []

        query_vec = self.llm.embed(self.settings.llm_embedding_model, [query])[0]
        if len(query_vec) != EMBEDDING_DIM:
            raise ValueError(
                f"query embedding dim mismatch: {len(query_vec)} vs {EMBEDDING_DIM}"
            )

        # pgvector cosine *distance* operator: <=> returns values in [0, 2]
        # for normalized vectors, but for unnormalized inputs the range is
        # [0, 2]. We bind the query as a vector literal and request the top
        # (k * 4) candidates, then filter by similarity post-hoc in case
        # the threshold drops some.
        sql = text(
            """
            SELECT
                c.id              AS chunk_id,
                c.item_id         AS item_id,
                i.title           AS item_title,
                c.text            AS text,
                1 - (c.embedding <=> :qvec) AS similarity
            FROM knowledge_base_chunk c
            JOIN knowledge_base_item i ON i.id = c.item_id
            WHERE c.tenant_id = :tid
            ORDER BY c.embedding <=> :qvec
            LIMIT :lim
            """
        )
        result = await self.session.execute(
            sql,
            {
                "qvec": f"[{','.join(str(x) for x in query_vec)}]",
                "tid": str(tenant_id),
                "lim": max(k * 4, k),
            },
        )
        out: list[RetrievedChunk] = []
        for row in result.mappings():
            sim = float(row["similarity"])
            if sim < min_sim:
                break  # rows are sorted by distance, so we can stop early
            out.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    item_id=row["item_id"],
                    item_title=row["item_title"],
                    text=row["text"],
                    similarity=sim,
                )
            )
            if len(out) >= k:
                break
        return out


# --- Helpers ----------------------------------------------------------------


def format_chunks_for_prompt(chunks: Iterable[RetrievedChunk]) -> str:
    """Format retrieved chunks for inclusion in the LLM prompt."""
    parts: list[str] = []
    for i, c in enumerate(chunks, start=1):
        parts.append(
            f"[{i}] (similarity={c.similarity:.2f}) {c.item_title}\n{c.text}"
        )
    return "\n\n".join(parts) if parts else "(no relevant case studies found)"
