"""Tools the research agent can call.

Each tool is a small, side-effect-free lookup that returns text the model can
reason over. Three rules keep this safe and affordable in a multi-tenant SaaS:

1. **Tenant-scoped.** Every tool receives the RLS-bound session and the
   tenant id. A tool can only ever see the calling tenant's data.
2. **Bounded output.** Each result is truncated, because tool output is fed
   straight back into the next completion and the tenant pays for those tokens.
3. **Never raises.** A failing tool returns an error string the model can read
   and route around. A dead scraper must not abort a draft.

Tool availability is dynamic: `search_web` only appears if the tenant has
connected a Serper key, so the model is never offered a tool that cannot work.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.llm import LLMClient
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.reply import Reply
from outreach_os.domain.models.send import Send

log = logging.getLogger(__name__)

# Tool results are re-sent with every subsequent completion, so an unbounded
# result would multiply the tenant's token bill on each loop iteration.
MAX_TOOL_RESULT_CHARS = 2000


@dataclass
class ToolContext:
    """Everything a tool needs, resolved once per agent run."""

    session: AsyncSession
    tenant_id: uuid.UUID
    lead_id: uuid.UUID
    # The tenant's own LLM client, for tools that need embeddings (RAG).
    llm: LLMClient
    # Decrypted, tenant-owned third-party keys (BYOK), keyed by credential kind.
    api_keys: dict[str, str]


ToolFn = Callable[[ToolContext, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: ToolFn

    def to_openai_schema(self) -> dict[str, Any]:
        """LiteLLM normalises this shape across providers."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# --- Tool implementations ---------------------------------------------------


async def _fetch_company_website(ctx: ToolContext, args: dict[str, Any]) -> str:
    """Scrape the lead's homepage for current positioning."""
    from outreach_os.services.scraping.live_research import scrape_live_context

    domain = str(args.get("domain") or "").strip()
    if not domain:
        lead = await ctx.session.get(Lead, ctx.lead_id)
        domain = (lead.domain if lead else None) or ""
    if not domain:
        return "No website domain is known for this lead."
    text = await asyncio.to_thread(scrape_live_context, domain)
    if not text:
        return f"Could not retrieve content from {domain} (blocked, empty, or offline)."
    return _truncate(text)


async def _search_knowledge_base(ctx: ToolContext, args: dict[str, Any]) -> str:
    """Semantic search over the customer's own uploaded case studies."""
    from outreach_os.services.rag_service import RAGService

    query = str(args.get("query") or "").strip()
    if not query:
        return "A non-empty 'query' is required."
    rag = RAGService(ctx.session, llm=ctx.llm)
    try:
        chunks = await rag.search(tenant_id=ctx.tenant_id, query=query)
    except Exception as exc:
        log.warning("knowledge base search failed: %s", exc)
        return "The knowledge base is unavailable right now."
    if not chunks:
        return "No relevant case studies found for that query."
    parts = [
        f"[{c.item_title}] (relevance {c.similarity:.2f})\n{c.text}" for c in chunks
    ]
    return _truncate("\n\n".join(parts))


async def _get_lead_profile(ctx: ToolContext, args: dict[str, Any]) -> str:
    """Everything already known about the lead from the database."""
    lead = await ctx.session.get(Lead, ctx.lead_id)
    if lead is None:
        return "Lead not found."
    profile = {
        "full_name": lead.full_name,
        "first_name": lead.first_name,
        "title": lead.title,
        "company_name": lead.company_name,
        "domain": lead.domain,
        "industry": lead.industry,
        "company_size": lead.company_size,
        "country": lead.country,
        "source": lead.source,
    }
    known = {k: v for k, v in profile.items() if v}
    extra = lead.raw_data or {}
    if isinstance(extra, dict) and extra.get("bio"):
        known["bio"] = str(extra["bio"])
    return _truncate(json.dumps(known, indent=2, default=str))


async def _get_previous_touches(ctx: ToolContext, args: dict[str, Any]) -> str:
    """Prior emails to, and replies from, this lead.

    Lets the model avoid repeating an angle that already failed, and reference
    an earlier message on follow-up steps.
    """
    sends = (
        (
            await ctx.session.execute(
                select(Send)
                .where(Send.tenant_id == ctx.tenant_id)
                .order_by(Send.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    if not sends:
        return "No previous emails have been sent to this lead."
    send_ids = [s.id for s in sends]
    replies = (
        (
            await ctx.session.execute(
                select(Reply)
                .where(
                    Reply.tenant_id == ctx.tenant_id,
                    Reply.send_id.in_(send_ids),
                )
                .order_by(Reply.received_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    lines = [
        f"SENT {s.sent_at:%Y-%m-%d}: {s.subject!r}" if s.sent_at else f"QUEUED: {s.subject!r}"
        for s in sends
    ]
    lines += [
        f"REPLY ({r.classification or 'unclassified'}): {(r.body_text or '')[:200]}"
        for r in replies
    ]
    return _truncate("\n".join(lines))


async def _search_web(ctx: ToolContext, args: dict[str, Any]) -> str:
    """Public web search, using the tenant's own Serper key."""
    from outreach_os.services.scraping.sources import serper

    query = str(args.get("query") or "").strip()
    if not query:
        return "A non-empty 'query' is required."
    api_key = ctx.api_keys.get("serper", "")
    if not api_key:
        return "Web search is unavailable: no Serper API key is connected."
    try:
        results = await asyncio.to_thread(
            serper.search, api_key=api_key, query=query, limit=5
        )
    except Exception as exc:
        log.warning("web search failed: %s", exc)
        return "Web search failed."
    if not results:
        return "No web results found."
    lines = []
    for r in results[:5]:
        raw = r.raw_data or {}
        lines.append(
            f"- {raw.get('title') or r.company_name or 'result'}: "
            f"{raw.get('snippet') or ''} ({raw.get('link') or ''})"
        )
    return _truncate("\n".join(lines))


# --- Registry ---------------------------------------------------------------

_ALL_TOOLS: tuple[Tool, ...] = (
    Tool(
        name="get_lead_profile",
        description=(
            "Return everything already stored about this lead (name, title, "
            "company, industry, size, country). Call this first — it is free "
            "and tells you what is already known."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        run=_get_lead_profile,
    ),
    Tool(
        name="fetch_company_website",
        description=(
            "Fetch the lead's company homepage and return its current "
            "positioning text. Use this to find a specific, current detail to "
            "personalise around."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Domain to fetch. Omit to use the lead's own domain.",
                }
            },
            "required": [],
        },
        run=_fetch_company_website,
    ),
    Tool(
        name="search_knowledge_base",
        description=(
            "Semantic search over the sender's own case studies and collateral. "
            "Use this to find at most one genuinely relevant proof point. "
            "Never cite a case study this returns nothing for."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look for, e.g. 'results for B2B SaaS sales teams'.",
                }
            },
            "required": ["query"],
        },
        run=_search_knowledge_base,
    ),
    Tool(
        name="get_previous_touches",
        description=(
            "List previous emails sent to this lead and any replies. Use this "
            "on follow-up steps so you can reference the earlier message and "
            "avoid repeating an angle that already failed."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        run=_get_previous_touches,
    ),
    Tool(
        name="search_web",
        description=(
            "Search the public web for recent news about the company (funding, "
            "launches, hiring). Only available if a Serper key is connected."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"],
        },
        run=_search_web,
    ),
)

# Tools that need a third-party key are only offered when that key exists —
# never advertise a capability the workspace cannot actually use.
_REQUIRES_KEY: dict[str, str] = {"search_web": "serper"}


def available_tools(api_keys: dict[str, str]) -> tuple[Tool, ...]:
    return tuple(
        t
        for t in _ALL_TOOLS
        if t.name not in _REQUIRES_KEY or api_keys.get(_REQUIRES_KEY[t.name])
    )


def tool_by_name(name: str) -> Tool | None:
    return next((t for t in _ALL_TOOLS if t.name == name), None)


__all__ = [
    "MAX_TOOL_RESULT_CHARS",
    "Tool",
    "ToolContext",
    "available_tools",
    "tool_by_name",
]
