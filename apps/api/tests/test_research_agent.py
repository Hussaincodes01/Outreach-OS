"""Tool-calling research agent: bounds and degradation.

An agent loop in a BYOK product spends the customer's money, so the properties
worth testing are not "does it write nice prose" but:

1. It stops at the step cap.
2. It stops when the token budget is spent.
3. A failing tool does not abort the run.
4. A provider without tool support degrades instead of failing.
5. Tools that need an un-connected key are never offered to the model.
6. Every tool call is recorded for audit.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from outreach_os.core.llm import LLMResponse, LLMUsage
from outreach_os.services.agent.research_agent import run_research_agent
from outreach_os.services.agent.tools import ToolContext, available_tools


class _ScriptedLLM:
    """Replays a fixed list of responses and records what it was asked."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(self, model: str, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        self.calls.append({"model": model, "messages": list(messages), **kwargs})
        if not self._responses:
            return LLMResponse(text="done", usage=LLMUsage(10, 10))
        return self._responses.pop(0)

    def embed(self, model: str, inputs: list[str], **kwargs: Any) -> list[list[float]]:
        return [[0.0] * 1536 for _ in inputs]


def _tool_call(name: str, args: dict[str, Any], call_id: str = "c1") -> LLMResponse:
    return LLMResponse(
        text="",
        usage=LLMUsage(100, 50),
        raw={"tool_calls": [{"id": call_id, "name": name, "arguments": json.dumps(args)}]},
    )


def _ctx(api_keys: dict[str, str] | None = None) -> ToolContext:
    # session is unused by the paths these tests drive; the tools that need it
    # are not the ones being exercised.
    return ToolContext(
        session=None,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        api_keys=api_keys or {},
    )


# --- tool availability ------------------------------------------------------


def test_web_search_is_hidden_without_a_serper_key() -> None:
    names = {t.name for t in available_tools({})}
    assert "search_web" not in names
    assert "get_lead_profile" in names


def test_web_search_appears_once_the_key_is_connected() -> None:
    names = {t.name for t in available_tools({"serper": "key"})}
    assert "search_web" in names


# --- bounds -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_stops_at_the_step_cap() -> None:
    """A model that keeps calling tools forever must be cut off."""
    llm = _ScriptedLLM([_tool_call("get_lead_profile", {}) for _ in range(20)])
    result = await run_research_agent(
        llm=llm,  # type: ignore[arg-type]
        model="openai/gpt-4o-mini",
        ctx=_ctx(),
        task_brief="research this lead",
        max_steps=3,
        max_tokens=1_000_000,
        timeout=10,
    )
    assert result.steps_used == 3
    assert result.stop_reason == "max_steps_reached"
    assert len(llm.calls) == 3, "must not exceed the step cap"


@pytest.mark.asyncio
async def test_loop_stops_when_the_token_budget_is_spent() -> None:
    """The tenant pays per token on their own key, so the budget is a hard stop."""
    llm = _ScriptedLLM([_tool_call("get_lead_profile", {}) for _ in range(20)])
    result = await run_research_agent(
        llm=llm,  # type: ignore[arg-type]
        model="openai/gpt-4o-mini",
        ctx=_ctx(),
        task_brief="research this lead",
        max_steps=50,
        max_tokens=200,  # each scripted round reports 150 tokens
        timeout=10,
    )
    assert result.stop_reason == "token_budget_exhausted"
    assert result.total_tokens >= 200
    assert len(llm.calls) < 50


@pytest.mark.asyncio
async def test_final_text_answer_ends_the_loop() -> None:
    llm = _ScriptedLLM(
        [
            _tool_call("get_lead_profile", {}),
            LLMResponse(text="Acme sells widgets. Hook: new funding.", usage=LLMUsage(80, 40)),
        ]
    )
    result = await run_research_agent(
        llm=llm,  # type: ignore[arg-type]
        model="openai/gpt-4o-mini",
        ctx=_ctx(),
        task_brief="research",
        max_steps=10,
        max_tokens=100_000,
        timeout=10,
    )
    assert result.stop_reason == "completed"
    assert "Acme sells widgets" in result.brief
    assert len(llm.calls) == 2


# --- degradation ------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_without_tool_support_degrades_instead_of_raising() -> None:
    """Not every model supports tool calling; that must not fail the draft."""

    class _NoTools:
        def chat(self, *a: Any, **k: Any) -> LLMResponse:
            from outreach_os.core.llm import LLMError

            raise LLMError("this model does not support tools")

        def embed(self, *a: Any, **k: Any) -> list[list[float]]:
            return []

    result = await run_research_agent(
        llm=_NoTools(),  # type: ignore[arg-type]
        model="some/model",
        ctx=_ctx(),
        task_brief="research",
        max_steps=5,
        max_tokens=100_000,
        timeout=10,
    )
    assert result.stop_reason == "llm_error"
    assert result.brief == ""  # caller falls back to deterministic research


@pytest.mark.asyncio
async def test_unknown_tool_is_reported_to_the_model_not_raised() -> None:
    llm = _ScriptedLLM(
        [
            _tool_call("definitely_not_a_tool", {}),
            LLMResponse(text="ok, done", usage=LLMUsage(10, 10)),
        ]
    )
    result = await run_research_agent(
        llm=llm,  # type: ignore[arg-type]
        model="openai/gpt-4o-mini",
        ctx=_ctx(),
        task_brief="research",
        max_steps=5,
        max_tokens=100_000,
        timeout=10,
    )
    assert result.brief == "ok, done"
    assert result.tool_calls[0].ok is False
    assert "Unknown or unavailable tool" in result.tool_calls[0].result_preview


@pytest.mark.asyncio
async def test_offering_a_tool_whose_key_is_missing_is_refused() -> None:
    """The model can hallucinate a tool name it wasn't given; it must not run."""
    llm = _ScriptedLLM(
        [
            _tool_call("search_web", {"query": "acme funding"}),
            LLMResponse(text="done", usage=LLMUsage(10, 10)),
        ]
    )
    result = await run_research_agent(
        llm=llm,  # type: ignore[arg-type]
        model="openai/gpt-4o-mini",
        ctx=_ctx(api_keys={}),  # no serper key
        task_brief="research",
        max_steps=5,
        max_tokens=100_000,
        timeout=10,
    )
    assert result.tool_calls[0].ok is False


# --- auditability -----------------------------------------------------------


@pytest.mark.asyncio
async def test_every_tool_call_is_recorded_in_the_trace() -> None:
    """agent_run.trace is the audit record for what the agent did and spent."""
    llm = _ScriptedLLM(
        [
            _tool_call("get_lead_profile", {}, call_id="a"),
            LLMResponse(text="brief", usage=LLMUsage(5, 5)),
        ]
    )
    result = await run_research_agent(
        llm=llm,  # type: ignore[arg-type]
        model="openai/gpt-4o-mini",
        ctx=_ctx(),
        task_brief="research",
        max_steps=5,
        max_tokens=100_000,
        timeout=10,
    )
    trace = result.to_trace()
    assert trace["steps_used"] == 2
    assert trace["stop_reason"] == "completed"
    assert trace["input_tokens"] > 0
    assert [c["name"] for c in trace["tool_calls"]] == ["get_lead_profile"]
