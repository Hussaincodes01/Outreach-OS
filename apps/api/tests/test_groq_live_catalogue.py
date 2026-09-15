"""Live check that every Groq model the app offers is actually served by Groq.

Groq retires models on short notice. A stale catalogue entry makes the
integrations Test button and drafting fail with `model_not_found`, and nothing
else in the suite can notice, because the catalogue is otherwise exercised
against fakes.

Skipped unless `OUTREACH_TEST_GROQ_KEY` is set. It is a test-only variable, so
the conftest fixture that clears `GROQ_API_KEY` never hides it.
"""
from __future__ import annotations

import os

import litellm
import pytest

from outreach_os.services.llm_credentials import PROVIDERS

pytestmark = pytest.mark.live_llm

_LIVE_KEY_ENV = "OUTREACH_TEST_GROQ_KEY"

_GROQ = next(p for p in PROVIDERS if p.provider == "groq")
_OFFERED_MODELS = sorted(
    {m.id for m in _GROQ.models} | ({_GROQ.verify_model} if _GROQ.verify_model else set())
)

_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_company",
        "description": "Look up a company by name.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}


@pytest.fixture
def groq_key() -> str:
    key = os.environ.get(_LIVE_KEY_ENV, "").strip()
    if not key:
        pytest.skip(f"{_LIVE_KEY_ENV} not set; skipping live Groq catalogue test")
    return key


@pytest.mark.parametrize("model", _OFFERED_MODELS)
async def test_groq_serves_every_offered_model(groq_key: str, model: str) -> None:
    response = await litellm.acompletion(
        model=model,
        api_key=groq_key,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        max_tokens=16,
        timeout=60,
    )
    assert response.choices, model


@pytest.mark.parametrize(
    "model", sorted(m.id for m in _GROQ.models if m.supports_tools)
)
async def test_groq_models_marked_tool_capable_accept_tools(
    groq_key: str, model: str
) -> None:
    """The research agent only attempts tool calling on models flagged capable;
    a wrong flag turns every draft on that model into a provider error."""
    response = await litellm.acompletion(
        model=model,
        api_key=groq_key,
        messages=[{"role": "user", "content": "Use the lookup_company tool for Acme."}],
        tools=[_LOOKUP_TOOL],
        tool_choice="auto",
        max_tokens=256,
        timeout=60,
    )
    assert response.choices, model
