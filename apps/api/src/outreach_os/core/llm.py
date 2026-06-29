"""LLM client — thin wrapper over LiteLLM.

Two surfaces:
- `chat(model, messages, ...)` for completions
- `embed(model, inputs)` for embeddings

We use LiteLLM so a campaign can route to any provider (OpenAI, Anthropic,
Gemini, Ollama, etc.) by changing the model name. Per-tenant API keys are
expected to be in the environment (e.g. `OPENAI_API_KEY`); the per-tenant
credential vault can be queried by callers to set them before invoking.

The wrapper is sync; LangGraph nodes call it from a `asyncio.to_thread` so
the event loop doesn't block on network I/O.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import litellm


@dataclass
class LLMUsage:
    """Token accounting for a single call."""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    # Raw provider response (for advanced callers / debugging).
    raw: dict[str, Any] | None = None


class LLMError(RuntimeError):
    """Raised on any LLM failure (auth, rate limit, timeout, content filter)."""


class LLMClient(Protocol):
    """Thin provider-agnostic surface used by LangGraph nodes."""

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 800,
        temperature: float = 0.7,
        timeout: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> LLMResponse: ...

    def embed(
        self,
        model: str,
        inputs: list[str],
        *,
        timeout: int | None = None,
    ) -> list[list[float]]: ...


def _to_litellm_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Validate the messages shape; LiteLLM is forgiving but we want a
    clear error early if a caller forgot the `role`."""
    for m in messages:
        if "role" not in m or "content" not in m:
            raise LLMError(f"LLM message missing 'role' or 'content': {m!r}")
    return messages


def _usage_from_response(resp: Any) -> LLMUsage:
    """Extract token counts from a LiteLLM response. Falls back to 0/0
    if the provider didn't return usage (some don't, e.g. older Ollama)."""
    try:
        usage = getattr(resp, "usage", None) or {}
        return LLMUsage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )
    except Exception:
        return LLMUsage()


class LiteLLMClient:
    """Default production client. Stateless — safe to share across requests."""

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 800,
        temperature: float = 0.7,
        timeout: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> LLMResponse:
        msgs = _to_litellm_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            resp = litellm.completion(**kwargs)
        except Exception as exc:
            raise LLMError(f"chat failed for model={model!r}: {exc}") from exc
        text = (resp.choices[0].message.content or "").strip()
        return LLMResponse(text=text, usage=_usage_from_response(resp))

    def embed(
        self,
        model: str,
        inputs: list[str],
        *,
        timeout: int | None = None,
    ) -> list[list[float]]:
        if not inputs:
            return []
        kwargs: dict[str, Any] = {"model": model, "input": inputs}
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            resp = litellm.embedding(**kwargs)
        except Exception as exc:
            raise LLMError(f"embed failed for model={model!r}: {exc}") from exc
        # LiteLLM returns EmbeddingResponse; .data is a list of {embedding: [...]}.
        return [list(item["embedding"]) for item in resp.data]


# --- Factory --------------------------------------------------------------

_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return the process-wide LLM client.

    Tests can monkeypatch this with a deterministic fake. The default
    is the LiteLLM-backed real client. If no provider key is set in the
    environment, fall back to a deterministic offline fake so local
    dev + the e2e demo still produce end-to-end runs.
    """
    global _default_client
    if _default_client is None:
        if not has_provider_credentials():
            # Lazy import to avoid a top-level dependency from the tests'
            # perspective (the fake lives in core/).
            from outreach_os.core.fake_llm import FakeLLMClient
            _default_client = FakeLLMClient()
        else:
            _default_client = LiteLLMClient()
    return _default_client


def set_llm_client(client: LLMClient | None) -> None:
    """Override the default client. Pass None to reset."""
    global _default_client
    _default_client = client


def has_provider_credentials() -> bool:
    """Cheap check: does *any* LiteLLM provider key exist in the env?

    Used by tests and the e2e demo to decide whether to skip live LLM calls.
    """
    keys = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "COHERE_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
    )
    return any(os.environ.get(k) for k in keys)


def has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))
