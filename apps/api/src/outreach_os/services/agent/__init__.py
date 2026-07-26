"""Campaign agent — 4-node LangGraph pipeline that produces a personalised
outreach email for one (campaign, lead, step) tuple.

Mirrors the kaymen99 graph shape (research -> niche -> style -> draft) but
implemented from scratch on top of LangGraph's `StateGraph` primitive.

Node responsibilities:
    research  : pull the lead from the DB and retrieve relevant RAG chunks.
    niche     : classify the lead's role/niche based on title + company.
    style     : distill the campaign's style guide (3 sample emails) into a
                a concrete voice recipe (length, sign-off, formality).
    draft     : compose the final subject + body using everything above.

We accumulate per-node inputs/outputs into the state's `trace` dict so the
run is debuggable from the `agent_run.trace` JSONB column.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.core.config import get_settings
from outreach_os.core.llm import LLMClient, LLMResponse
from outreach_os.domain.models.campaign import Campaign
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.tenant import Tenant
from outreach_os.services.agent.research_agent import run_research_agent
from outreach_os.services.agent.tools import ToolContext
from outreach_os.services.credential_lookup import get_credential_secrets
from outreach_os.services.llm_credentials import client_for
from outreach_os.services.rag_service import RAGService, RetrievedChunk, format_chunks_for_prompt
from outreach_os.services.scraping.live_research import scrape_live_context

log = logging.getLogger(__name__)


# --- State -----------------------------------------------------------------


@dataclass
class AgentState:
    """Mutable state passed between nodes. LangGraph's StateGraph will copy
    it between nodes; we use field(default_factory=...) for collections."""

    # Inputs (set once before invoke)
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    campaign_id: uuid.UUID = field(default_factory=uuid.uuid4)
    lead_id: uuid.UUID = field(default_factory=uuid.uuid4)
    step_id: uuid.UUID = field(default_factory=uuid.uuid4)
    model: str = ""

    # Populated by nodes
    lead: dict[str, Any] = field(default_factory=dict)
    campaign: dict[str, Any] = field(default_factory=dict)
    step: dict[str, Any] = field(default_factory=dict)
    rag_chunks: list[dict[str, Any]] = field(default_factory=list)
    live_context: str = ""
    niche: dict[str, Any] = field(default_factory=dict)
    style: dict[str, Any] = field(default_factory=dict)
    draft_subject: str = ""
    draft_body: str = ""

    # Per-node token accounting
    input_tokens: int = 0
    output_tokens: int = 0

    # Per-node trace (for debugging + agent_run.trace JSONB)
    trace: dict[str, Any] = field(default_factory=dict)

    # Final outcome
    error: str | None = None


# --- Domain loaders (used by the research node) --------------------------


async def _load_lead(session: AsyncSession, lead_id: uuid.UUID) -> Lead:
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise AgentInputError(f"lead {lead_id} not found")
    return lead


async def _load_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    result = await session.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise AgentInputError(f"campaign {campaign_id} not found")
    return campaign


async def _load_step(session: AsyncSession, step_id: uuid.UUID) -> CampaignStep:
    result = await session.execute(
        select(CampaignStep).where(CampaignStep.id == step_id)
    )
    step = result.scalar_one_or_none()
    if step is None:
        raise AgentInputError(f"campaign_step {step_id} not found")
    return step


# --- Node prompts ----------------------------------------------------------

_NICHE_SYSTEM = """\
You classify a B2B sales lead's "niche" — their functional role and
likely concerns — to help tailor outreach. Output strict JSON.

Return a JSON object with these fields:
  role_seniority: "IC" | "Manager" | "Director" | "VP" | "C-suite" | "Other"
  function:       "Sales" | "Marketing" | "Engineering" | "Operations" |
                  "Finance" | "Customer Success" | "Product" | "Other"
  primary_concern: one-sentence guess of their top business concern
  buying_window:   "immediate" | "this_quarter" | "this_year" | "exploratory"
"""


_STYLE_SYSTEM = """\
You are a writing-coach. Given up to 3 sample emails the customer wrote,
extract a precise "voice recipe" the model should imitate. Output strict JSON.

Return a JSON object with these fields:
  tone:           one of "formal" | "casual" | "mixed"
  greeting:       the typical opening line (e.g. "Hi {first_name},")
  sign_off:       the typical closing line
  avg_length:     one of "short" (<80 words) | "medium" (80-150) | "long" (>150)
  signature:      a distinctive phrase or pattern they reuse (e.g. "specific" or
                  "no fluff")
  avoid:          list of words or patterns to avoid (e.g. ["synergy", "circle back"])
"""


_DRAFT_SYSTEM = """\
You write a single, personalised B2B cold-outreach email.

Inputs you are given:
- LEAD: their name, title, company, and what you know about them.
- NICHE: their role, function, top concern, and buying window.
- STYLE: a voice recipe distilled from the customer's own emails.
- CASE_STUDIES: 0-4 case-study excerpts the customer uploaded (use sparingly).
- STEP: which step in the sequence this is (1 = opener, 2+ = follow-up).
- SUBJECT_TEMPLATE: a placeholder the customer picked; you may rewrite freely
  as long as the meaning is preserved.

Hard rules:
- Output must be a JSON object with exactly two fields:
    subject: a short subject line, <= 80 chars, no leading "Re:" unless STEP > 1
    body:    the email body, plain text, 80-160 words
- No placeholders. No "[Company Name]". No fabricated stats.
- If the lead's data is too thin, use a safe, generic opener — do not invent.
- Never promise discounts, case studies, or meetings the customer hasn't set.
- Respect the STYLE voice recipe precisely. Mirror greeting + sign-off.
- Mention 0-1 case study, only if it is clearly relevant to the niche.
- If STEP > 1, the email must reference a prior touch (e.g. "bumping this up").
"""


# --- Nodes -----------------------------------------------------------------


def _to_chat_response(resp: LLMResponse) -> dict[str, Any]:
    """Tag a response for the trace dict."""
    return {
        "text": resp.text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }


def _try_parse_json(text_str: str) -> dict[str, Any] | None:
    """Tolerant JSON parse for LLM output that may have leading/trailing
    prose around a JSON object."""
    if not text_str:
        return None
    text_str = text_str.strip()
    try:
        return cast("dict[str, Any] | None", json.loads(text_str))
    except json.JSONDecodeError:
        pass
    # Find the first '{' and last '}'.
    start = text_str.find("{")
    end = text_str.rfind("}")
    if start >= 0 and end > start:
        try:
            return cast("dict[str, Any] | None", json.loads(text_str[start : end + 1]))
        except json.JSONDecodeError:
            return None
    return None


class AgentInputError(RuntimeError):
    """Raised when the inputs (lead/campaign/step) are missing or invalid."""


async def _run_tool_research(
    *,
    session: AsyncSession,
    llm: LLMClient,
    state: AgentState,
    lead: Lead,
    campaign: Campaign,
    step: CampaignStep,
) -> tuple[str, dict[str, Any]]:
    """Run the tool-calling researcher. Returns (brief, trace).

    Returns an empty brief on any failure so the caller can fall back; research
    is an enhancement, never a reason to fail a draft.
    """
    settings = get_settings()
    try:
        # Third-party keys are BYOK too — the web-search tool only appears if
        # this tenant connected their own Serper key.
        api_keys = await get_credential_secrets(
            session, tenant_id=state.tenant_id, kinds=["serper"]
        )
        ctx = ToolContext(
            session=session,
            tenant_id=state.tenant_id,
            lead_id=state.lead_id,
            llm=llm,
            api_keys=api_keys,
        )
        task = (
            f"Lead: {lead.full_name or lead.first_name or 'unknown'}"
            f" — {lead.title or 'unknown title'}"
            f" at {lead.company_name or lead.domain or 'unknown company'}.\n"
            f"Campaign: {campaign.name}. Goal of this email: {step.goal or 'open a conversation'}.\n"
            f"This is step {step.step_number} of the sequence."
        )
        result = await run_research_agent(
            llm=llm,
            model=state.model,
            ctx=ctx,
            task_brief=task,
            max_steps=settings.agent_max_tool_steps,
            max_tokens=settings.agent_max_research_tokens,
            timeout=settings.llm_request_timeout,
        )
    except Exception as exc:
        log.warning("research agent failed, falling back: %s", exc)
        return "", {"error": str(exc)[:200]}

    return result.brief, result.to_trace()


async def _node_research(
    state: AgentState,
    *,
    session: AsyncSession,
    llm: LLMClient,
) -> dict[str, Any]:
    settings = get_settings()
    lead = await _load_lead(session, state.lead_id)
    campaign = await _load_campaign(session, state.campaign_id)
    step = await _load_step(session, state.step_id)

    # RAG: build a query from the lead + step, return top-k chunks.
    rag = RAGService(session, llm=llm)
    query = f"{step.goal or ''} {lead.title or ''} {lead.company_name or ''} {lead.industry or ''}".strip()
    chunks: list[RetrievedChunk] = []
    if query:
        try:
            chunks = await rag.search(tenant_id=state.tenant_id, query=query)
        except Exception as exc:
            # RAG failure must not abort the run; we just skip it.
            log.warning("rag search failed: %s", exc)

    # Agentic research: let the model decide what to look up. Falls back to the
    # deterministic homepage scrape when disabled, unsupported by the provider,
    # or unproductive — a draft is always produced.
    research_brief = ""
    research_trace: dict[str, Any] = {}
    if settings.agent_tools_enabled:
        research_brief, research_trace = await _run_tool_research(
            session=session,
            llm=llm,
            state=state,
            lead=lead,
            campaign=campaign,
            step=step,
        )

    live_ctx = research_brief
    if not live_ctx:
        live_ctx = await asyncio.to_thread(scrape_live_context, lead.domain)
        research_trace = {**research_trace, "fallback": "deterministic_scrape"}

    return {
        "lead": {
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "full_name": lead.full_name,
            "email": lead.email,
            "title": lead.title,
            "company_name": lead.company_name,
            "domain": lead.domain,
            "industry": lead.industry,
            "company_size": lead.company_size,
            "country": lead.country,
        },
        "campaign": {
            "name": campaign.name,
            "description": campaign.description,
            "style_notes": campaign.style_notes,
            "style_sample_emails": list(campaign.style_sample_emails or []),
        },
        "step": {
            "step_number": step.step_number,
            "delay_days": step.delay_days,
            "subject_template": step.subject_template,
            "goal": step.goal,
        },
        "rag_chunks": [
            {
                "item_id": str(c.item_id),
                "item_title": c.item_title,
                "text": c.text,
                "similarity": c.similarity,
            }
            for c in chunks
        ],
        "live_context": live_ctx,
        "trace": {
            "research": {
                "query": query,
                "rag_chunk_count": len(chunks),
                "live_context_chars": len(live_ctx),
                "agent": research_trace,
            }
        },
    }


async def _node_niche(
    state: AgentState, *, llm: LLMClient
) -> dict[str, Any]:
    lead = state.lead
    user_prompt = (
        f"Lead title: {lead.get('title') or 'unknown'}\n"
        f"Lead company: {lead.get('company_name') or lead.get('domain') or 'unknown'}\n"
        f"Lead industry: {lead.get('industry') or 'unknown'}\n"
        f"Company size: {lead.get('company_size') or 'unknown'}\n"
        f"Country: {lead.get('country') or 'unknown'}\n"
    )
    # Run the LLM off the event loop. LiteLLM is sync.
    resp = await asyncio.to_thread(
        llm.chat,
        state.model,
        [
            {"role": "system", "content": _NICHE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=get_settings().llm_classify_max_tokens,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    parsed = _try_parse_json(resp.text) or {}
    return {
        "niche": parsed,
        "input_tokens": state.input_tokens + resp.usage.input_tokens,
        "output_tokens": state.output_tokens + resp.usage.output_tokens,
        "trace": {**state.trace, "niche": {**_to_chat_response(resp), "parsed": parsed}},
    }


async def _node_style(
    state: AgentState, *, llm: LLMClient
) -> dict[str, Any]:
    samples = (state.campaign or {}).get("style_sample_emails") or []
    notes = (state.campaign or {}).get("style_notes")
    if not samples and not notes:
        # Nothing to learn from. Provide a default recipe.
        return {
            "style": {
                "tone": "casual",
                "greeting": "Hi {first_name},",
                "sign_off": "Best,",
                "avg_length": "short",
                "signature": "specific",
                "avoid": ["synergy", "circle back"],
            },
            "trace": {**state.trace, "style": {"note": "no samples provided, used defaults"}},
        }
    user_prompt_parts: list[str] = []
    if notes:
        user_prompt_parts.append(f"Customer style notes: {notes}")
    for i, s in enumerate(samples, start=1):
        user_prompt_parts.append(f"--- Sample {i} ---\n{s}")
    user_prompt = "\n\n".join(user_prompt_parts)
    resp = await asyncio.to_thread(
        llm.chat,
        state.model,
        [
            {"role": "system", "content": _STYLE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=get_settings().llm_classify_max_tokens,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    parsed = _try_parse_json(resp.text) or {}
    return {
        "style": parsed,
        "input_tokens": state.input_tokens + resp.usage.input_tokens,
        "output_tokens": state.output_tokens + resp.usage.output_tokens,
        "trace": {**state.trace, "style": {**_to_chat_response(resp), "parsed": parsed}},
    }


async def _node_draft(
    state: AgentState, *, llm: LLMClient
) -> dict[str, Any]:
    lead = state.lead
    step = state.step
    chunks_text = format_chunks_for_prompt(
        [
            RetrievedChunk(
                chunk_id=uuid.UUID(c["item_id"]),  # approximate; not used in prompt
                item_id=uuid.UUID(c["item_id"]),
                item_title=c["item_title"],
                text=c["text"],
                similarity=c["similarity"],
            )
            for c in state.rag_chunks
        ]
    )
    style = state.style
    user_prompt = (
        f"LEAD:\n{json.dumps(lead, default=str, indent=2)}\n\n"
        f"NICHE:\n{json.dumps(state.niche, default=str, indent=2)}\n\n"
        f"STYLE (follow this voice):\n{json.dumps(style, default=str, indent=2)}\n\n"
        f"STEP:\n{json.dumps(step, default=str, indent=2)}\n\n"
        f"SUBJECT_TEMPLATE: {step.get('subject_template')}\n\n"
        f"CASE_STUDIES (use at most one if relevant):\n{chunks_text}\n"
    )
    if state.live_context:
        user_prompt += f"\nLIVE COMPANY CONTEXT (from their website, use if relevant):\n{state.live_context}\n"
    resp = await asyncio.to_thread(
        llm.chat,
        state.model,
        [
            {"role": "system", "content": _DRAFT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=get_settings().llm_draft_max_tokens,
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    parsed = _try_parse_json(resp.text) or {}
    subject = str(parsed.get("subject") or step.get("subject_template") or "Quick question").strip()
    body = str(parsed.get("body") or "").strip()
    return {
        "draft_subject": subject,
        "draft_body": body,
        "input_tokens": state.input_tokens + resp.usage.input_tokens,
        "output_tokens": state.output_tokens + resp.usage.output_tokens,
        "trace": {
            **state.trace,
            "draft": {**_to_chat_response(resp), "parsed": parsed},
        },
    }


# --- Graph -----------------------------------------------------------------


def build_graph() -> Any:
    """Return a compiled LangGraph graph. We use RunnableConfig to pass
    per-run dependencies (session, llm) into each node — the graph itself
    is stateless and reusable across requests/tenants."""
    from langchain_core.runnables import RunnableConfig

    g = StateGraph(AgentState)

    async def research(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        return await _node_research(
            state, session=config["configurable"]["session"], llm=config["configurable"]["llm"]
        )

    async def niche(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        return await _node_niche(state, llm=config["configurable"]["llm"])

    async def style(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        return await _node_style(state, llm=config["configurable"]["llm"])

    async def draft(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        return await _node_draft(state, llm=config["configurable"]["llm"])

    g.add_node("research", research)
    g.add_node("niche", niche)
    g.add_node("style", style)
    g.add_node("draft", draft)
    g.add_edge(START, "research")
    g.add_edge("research", "niche")
    g.add_edge("niche", "style")
    g.add_edge("style", "draft")
    g.add_edge("draft", END)
    return g.compile()


_compiled = None


def get_graph() -> Any:
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


# --- Public entry point ----------------------------------------------------


@dataclass
class AgentRunResult:
    subject: str
    body: str
    input_tokens: int
    output_tokens: int
    trace: dict[str, Any]
    model: str
    started_at: datetime
    completed_at: datetime


async def run_agent(
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    lead_id: uuid.UUID,
    step_id: uuid.UUID,
    llm: LLMClient | None = None,
) -> AgentRunResult:
    """Run the 4-node pipeline end-to-end. The caller is responsible for
    persisting the `AgentRun` row and the resulting `Draft`."""
    settings = get_settings()

    # Model resolution, most specific first: this campaign's override, then the
    # workspace's chosen model, then the server default.
    campaign = await _load_campaign(session, campaign_id)
    tenant = await session.get(Tenant, tenant_id)
    model = (
        campaign.llm_model
        or (tenant.default_llm_model if tenant else None)
        or settings.llm_default_model
    )

    # BYOK: bind the client to this tenant's own key for the chosen model's
    # provider. Resolved AFTER the model is known, since the model decides
    # which provider credential we need.
    llm = await client_for(session, tenant_id=tenant_id, model=model, injected=llm)

    state = AgentState(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        step_id=step_id,
        model=model,
    )

    started = datetime.utcnow()
    graph = get_graph()
    # ainvoke() runs the async graph in the current event loop. Per-run
    # deps are passed through `configurable` (the LangGraph-recommended way).
    final_dict: dict[str, Any] = await graph.ainvoke(
        state,
        config={"configurable": {"session": session, "llm": llm}},
    )
    completed = datetime.utcnow()

    # LangGraph may return the state as a dict; reconstruct.
    if isinstance(final_dict, dict):
        subject = final_dict.get("draft_subject", "") or ""
        body = final_dict.get("draft_body", "") or ""
        in_tok = int(final_dict.get("input_tokens", 0) or 0)
        out_tok = int(final_dict.get("output_tokens", 0) or 0)
        trace = final_dict.get("trace", {}) or {}
    else:
        subject = final_dict.draft_subject
        body = final_dict.draft_body
        in_tok = final_dict.input_tokens
        out_tok = final_dict.output_tokens
        trace = final_dict.trace

    return AgentRunResult(
        subject=subject,
        body=body,
        input_tokens=in_tok,
        output_tokens=out_tok,
        trace=trace,
        model=model,
        started_at=started,
        completed_at=completed,
    )
