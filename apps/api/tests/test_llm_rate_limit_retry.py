"""A rate-limited LLM call waits as the provider asks and retries.

Free-tier provider plans (Groq's 1,000 output tokens per minute, for one)
reject a burst of agent calls with HTTP 429 and say exactly how long to wait.
Treating that as a permanent failure turned every draft into status=failed.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from litellm import BadRequestError, RateLimitError

from outreach_os.core import llm
from outreach_os.core.llm import LiteLLMClient, LLMCredentials, LLMError

_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _rate_limited(retry_after: str | None, message: str = "Rate limit reached.") -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return RateLimitError(
        message=message,
        llm_provider="groq",
        model="groq/qwen/qwen3.8-27b",
        response=httpx.Response(429, headers=headers, request=_REQUEST),
    )


def _completion(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
    )


class _ScriptedCompletion:
    """Stands in for litellm.completion: raises the scripted errors in order,
    then returns a completion."""

    def __init__(self, errors: list[Exception]) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return _completion("drafted")


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(llm, "_sleep", recorded.append, raising=False)
    return recorded


def _client() -> LiteLLMClient:
    return LiteLLMClient(LLMCredentials(provider="groq", api_key="gsk-test"))


def _chat(client: LiteLLMClient):
    return client.chat("groq/qwen/qwen3.8-27b", [{"role": "user", "content": "hi"}])


def test_rate_limited_call_waits_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, waits: list[float]
) -> None:
    scripted = _ScriptedCompletion([_rate_limited("12")])
    monkeypatch.setattr(llm.litellm, "completion", scripted)

    response = _chat(_client())

    assert response.text == "drafted"
    assert scripted.calls == 2
    assert waits == [12.0]


def test_wait_is_read_from_the_message_when_no_header(
    monkeypatch: pytest.MonkeyPatch, waits: list[float]
) -> None:
    scripted = _ScriptedCompletion(
        [_rate_limited(None, "Please try again in 12.48s. Need more tokens?")]
    )
    monkeypatch.setattr(llm.litellm, "completion", scripted)

    assert _chat(_client()).text == "drafted"
    assert waits == [12.48]


def test_gives_up_after_three_retries_with_capped_waits(
    monkeypatch: pytest.MonkeyPatch, waits: list[float]
) -> None:
    scripted = _ScriptedCompletion([_rate_limited("90") for _ in range(10)])
    monkeypatch.setattr(llm.litellm, "completion", scripted)

    with pytest.raises(LLMError, match="chat failed"):
        _chat(_client())

    assert scripted.calls == 4
    assert waits == [30.0, 30.0, 30.0]


def test_other_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, waits: list[float]
) -> None:
    bad_request = BadRequestError(
        message="`tool calling` is not supported with this model",
        model="groq/groq/compound-mini",
        llm_provider="groq",
    )
    scripted = _ScriptedCompletion([bad_request])
    monkeypatch.setattr(llm.litellm, "completion", scripted)

    with pytest.raises(LLMError):
        _chat(_client())

    assert scripted.calls == 1
    assert waits == []
