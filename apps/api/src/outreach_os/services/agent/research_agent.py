"""Tool-calling research agent.

Replaces the old fixed "scrape the homepage + one RAG query" research step.
The model now decides what it needs: it may check what is already known, pull
the company site, look for a relevant case study, check whether this lead has
been emailed before, or search the web — in whatever order makes sense for the
lead in front of it.

Cost is bounded on three independent axes, because the tenant pays for every
token on their own key:

- `max_steps`      — hard cap on tool-calling rounds
- `max_tokens`     — cumulative budget across the loop; exceeded, we stop
- per-tool output  — truncated in `tools.py`

Degradation is deliberate: if the provider does not support tool calling, or
the loop yields nothing, the caller falls back to the deterministic research
path. A draft is always produced.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from outreach_os.core.llm import LLMClient, LLMError
from outreach_os.services.agent.tools import (
    Tool,
    ToolContext,
    available_tools,
    tool_by_name,
)

log = logging.getLogger(__name__)

_RESEARCH_SYSTEM = """\
You are a B2B sales researcher. Your job is to gather the specific facts a
colleague needs to write ONE personalised cold email to a single lead.

Work by calling the tools available to you. Guidelines:
- Start with `get_lead_profile` to see what is already known.
- Prefer ONE concrete, current, verifiable detail over many vague ones.
- On a follow-up step (step_number > 1), always call `get_previous_touches`.
- Call `search_knowledge_base` at most once, and only if a proof point would
  genuinely land for this lead's role and industry.
- Stop as soon as you have enough. Extra calls cost the user money.

When you are done, reply with a plain-text research brief of at most 200 words:
- What the company does, in one line.
- The single best hook to open with, and where it came from.
- One relevant proof point, or "none" if the knowledge base had nothing.
- Anything to avoid (e.g. an angle already tried in a previous email).

Never invent facts. If a tool returns nothing useful, say so plainly.
"""


@dataclass
class ToolCallRecord:
    """One tool invocation, kept for the agent_run trace."""

    step: int
    name: str
    arguments: dict[str, Any]
    result_preview: str
    ok: bool = True


@dataclass
class ResearchResult:
    brief: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    steps_used: int = 0
    stop_reason: str = "completed"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_trace(self) -> dict[str, Any]:
        return {
            "brief_chars": len(self.brief),
            "steps_used": self.steps_used,
            "stop_reason": self.stop_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": [
                {
                    "step": c.step,
                    "name": c.name,
                    "arguments": c.arguments,
                    "ok": c.ok,
                    "result_preview": c.result_preview[:200],
                }
                for c in self.tool_calls
            ],
        }


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string; models occasionally emit junk."""
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _run_tool(tool: Tool, ctx: ToolContext, args: dict[str, Any]) -> tuple[str, bool]:
    try:
        return await tool.run(ctx, args), True
    except Exception as exc:
        log.warning("tool %s failed: %s", tool.name, exc)
        return f"Tool '{tool.name}' failed: {exc}", False


async def run_research_agent(
    *,
    llm: LLMClient,
    model: str,
    ctx: ToolContext,
    task_brief: str,
    max_steps: int,
    max_tokens: int,
    timeout: int,
) -> ResearchResult:
    """Drive the tool-calling loop and return a research brief.

    Never raises for model/tool problems: a degraded brief still lets the
    downstream draft node produce an email.
    """
    tools = available_tools(ctx.api_keys)
    schemas = [t.to_openai_schema() for t in tools]
    result = ResearchResult()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _RESEARCH_SYSTEM},
        {"role": "user", "content": task_brief},
    ]

    for step in range(1, max_steps + 1):
        result.steps_used = step

        if result.total_tokens >= max_tokens:
            result.stop_reason = "token_budget_exhausted"
            break

        try:
            resp = await asyncio.to_thread(
                llm.chat,
                model,
                messages,
                max_tokens=600,
                temperature=0.3,
                timeout=timeout,
                tools=schemas,
            )
        except LLMError as exc:
            # Most likely: this provider/model has no tool-calling support.
            log.info("research agent stopped at step %d: %s", step, exc)
            result.stop_reason = "llm_error"
            break

        result.input_tokens += resp.usage.input_tokens
        result.output_tokens += resp.usage.output_tokens

        calls = (resp.raw or {}).get("tool_calls") or []
        if not calls:
            # No tool requested -> the model is answering, i.e. it's done.
            result.brief = resp.text.strip()
            result.stop_reason = "completed"
            break

        # Echo the assistant turn back so the model sees its own tool calls.
        messages.append(
            {
                "role": "assistant",
                "content": resp.text or "",
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in calls
                ],
            }
        )

        for call in calls:
            name = str(call.get("name") or "")
            args = _parse_arguments(call.get("arguments"))
            tool = tool_by_name(name)
            if tool is None or tool not in tools:
                output, ok = f"Unknown or unavailable tool: {name!r}", False
            else:
                output, ok = await _run_tool(tool, ctx, args)
            result.tool_calls.append(
                ToolCallRecord(
                    step=step, name=name, arguments=args, result_preview=output, ok=ok
                )
            )
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": output}
            )
    else:
        # Loop ran to the cap without the model volunteering a final answer.
        result.stop_reason = "max_steps_reached"

    if not result.brief and result.tool_calls:
        # Out of steps or budget mid-investigation: salvage what the tools
        # returned so the draft node still has something concrete to use.
        result.brief = "\n\n".join(
            f"{c.name}: {c.result_preview}" for c in result.tool_calls if c.ok
        )[:2000]

    return result


__all__ = ["ResearchResult", "ToolCallRecord", "run_research_agent"]
