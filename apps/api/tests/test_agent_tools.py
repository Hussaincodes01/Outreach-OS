"""Contract between the test double and the real LLM client.

`test_research_agent.py` drives the loop with its own `_ScriptedLLM`, so it
never exercises `tests/fake_llm.FakeLLMClient` — which is precisely how that
fake drifted out of sync with `LLMClient`. When `chat()` gained a `tools`
parameter, every call through the shared fake raised TypeError, the agent's
broad handler swallowed it, and the tool loop silently stopped running in the
draft-pipeline tests.

Comparing the signatures directly is the cheapest way to stop that recurring.
"""
from __future__ import annotations

import inspect

import pytest

from outreach_os.core.llm import LiteLLMClient, LLMClient
from tests.fake_llm import FakeLLMClient


@pytest.mark.parametrize("method", ["chat", "embed"])
def test_fake_client_matches_the_real_client(method: str) -> None:
    real = inspect.signature(getattr(LiteLLMClient, method)).parameters
    fake = inspect.signature(getattr(FakeLLMClient, method)).parameters
    missing = set(real) - set(fake)
    assert not missing, (
        f"FakeLLMClient.{method} is missing {sorted(missing)}; calls through the "
        f"shared fake will raise TypeError and be swallowed by callers"
    )


@pytest.mark.parametrize("method", ["chat", "embed"])
def test_fake_client_satisfies_the_protocol(method: str) -> None:
    """The Protocol is what services are typed against."""
    protocol = inspect.signature(getattr(LLMClient, method)).parameters
    fake = inspect.signature(getattr(FakeLLMClient, method)).parameters
    assert not set(protocol) - set(fake)


def test_fake_returns_tool_calls_on_raw_like_the_real_client() -> None:
    """The agent reads tool calls from `raw`, not from the text body."""
    fake = FakeLLMClient()
    fake.next_tool_calls = [[{"id": "c1", "name": "get_lead_profile", "arguments": "{}"}]]
    resp = fake.chat(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "get_lead_profile"}}],
    )
    assert resp.raw is not None
    assert resp.raw["tool_calls"][0]["name"] == "get_lead_profile"
    assert resp.text == ""


def test_fake_answers_normally_when_no_tool_calls_are_queued() -> None:
    """An empty queue is how the loop terminates."""
    fake = FakeLLMClient()
    resp = fake.chat(
        "openai/gpt-4o-mini",
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "get_lead_profile"}}],
    )
    assert resp.raw is None or not (resp.raw or {}).get("tool_calls")
