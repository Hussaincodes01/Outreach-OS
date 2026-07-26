"""LLM client — thin wrapper over LiteLLM, with per-tenant (BYOK) credentials.

Two surfaces:
- `chat(model, messages, ...)` for completions
- `embed(model, inputs)` for embeddings

**Bring Your Own Key.** Credentials are NEVER read from the process
environment. Each call passes an explicit `api_key`/`api_base` resolved from
the calling tenant's encrypted vault (see `services.llm_credentials`). This is
the only correct option in a shared worker: a Celery process serves many
tenants concurrently, so mutating `os.environ` per call would leak one
tenant's key into another tenant's request.

The wrapper is sync; LangGraph nodes call it from `asyncio.to_thread` so the
event loop doesn't block on network I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import litellm


@dataclass(frozen=True)
class LLMCredentials:
    """A single tenant's credentials for one provider."""

    provider: str
    api_key: str
    # Optional override for self-hosted / proxied deployments (Ollama, Azure,
    # vLLM, OpenRouter, ...).
    api_base: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - defensive
        """Never let a key reach a log line or traceback via repr."""
        return f"LLMCredentials(provider={self.provider!r}, api_key='***', api_base={self.api_base!r})"


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


class LLMAuthError(LLMError):
    """The tenant's key was rejected by the provider.

    Separate from LLMError so the API layer can return 402/400 with a
    "check your API key" message instead of a generic 500.
    """


# Providers echo the key back in some error payloads; scrub anything that
# looks like a secret before it reaches a log or an API response.
_SECRET_RE = re.compile(
    r"\b(sk-[A-Za-z0-9_\-]{8,}|xai-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{8,}"
    r"|gsk_[A-Za-z0-9_\-]{8,}|[A-Za-z0-9_\-]{32,})\b"
)


def redact(text: str) -> str:
    """Mask anything key-shaped in provider error text."""
    return _SECRET_RE.sub("***", text)


def _is_auth_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if "authentication" in name or "permissiondenied" in name:
        return True
    status = getattr(exc, "status_code", None)
    return status in (401, 403)


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
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...

    def embed(
        self,
        model: str,
        inputs: list[str],
        *,
        timeout: int | None = None,
        dimensions: int | None = None,
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
    """Production client, bound to one tenant's credentials.

    Construct one per run via `services.llm_credentials.resolve_llm_client`.
    The instance holds no mutable state beyond its credentials, so it is safe
    to use across threads for the lifetime of a single agent run.
    """

    def __init__(self, credentials: LLMCredentials) -> None:
        self._credentials = credentials

    @property
    def provider(self) -> str:
        return self._credentials.provider

    def _auth_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"api_key": self._credentials.api_key}
        if self._credentials.api_base:
            kwargs["api_base"] = self._credentials.api_base
        return kwargs

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 800,
        temperature: float = 0.7,
        timeout: int | None = None,
        response_format: dict[str, str] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        msgs = _to_litellm_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **self._auth_kwargs(),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            resp = litellm.completion(**kwargs)
        except Exception as exc:
            detail = redact(str(exc))
            if _is_auth_error(exc):
                raise LLMAuthError(
                    f"{self._credentials.provider} rejected the API key: {detail}"
                ) from exc
            raise LLMError(f"chat failed for model={model!r}: {detail}") from exc
        choice = resp.choices[0].message
        text = (choice.content or "").strip()
        raw: dict[str, Any] | None = None
        tool_calls = getattr(choice, "tool_calls", None)
        if tool_calls:
            # Surface tool calls to the agent loop without leaking the SDK type.
            raw = {
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in tool_calls
                ]
            }
        return LLMResponse(text=text, usage=_usage_from_response(resp), raw=raw)

    def embed(
        self,
        model: str,
        inputs: list[str],
        *,
        timeout: int | None = None,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        if not inputs:
            return []
        kwargs: dict[str, Any] = {
            "model": model,
            "input": inputs,
            **self._auth_kwargs(),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if dimensions is not None:
            # OpenAI v3 embeddings can project to a smaller width, which is how
            # text-embedding-3-large fits our fixed-width vector column.
            kwargs["dimensions"] = dimensions
        try:
            resp = litellm.embedding(**kwargs)
        except Exception as exc:
            detail = redact(str(exc))
            if _is_auth_error(exc):
                raise LLMAuthError(
                    f"{self._credentials.provider} rejected the API key: {detail}"
                ) from exc
            raise LLMError(f"embed failed for model={model!r}: {detail}") from exc
        # LiteLLM returns EmbeddingResponse; .data is a list of {embedding: [...]}.
        return [list(item["embedding"]) for item in resp.data]


# --- Test / override seam --------------------------------------------------
#
# There is deliberately no "default" production client: a real client cannot
# exist without a tenant's key. `set_llm_client` exists so the test suite (and
# the offline demo) can inject a deterministic fake; production leaves it unset
# and every call site resolves a tenant-scoped client instead.

_override_client: LLMClient | None = None


def get_llm_client() -> LLMClient | None:
    """Return the injected override client, or None if none is set.

    Returning None is the normal production case — callers must then resolve a
    tenant-scoped client via `services.llm_credentials.resolve_llm_client`.
    """
    return _override_client


def set_llm_client(client: LLMClient | None) -> None:
    """Override the client process-wide. Pass None to reset."""
    global _override_client
    _override_client = client


__all__ = [
    "LLMAuthError",
    "LLMClient",
    "LLMCredentials",
    "LLMError",
    "LLMResponse",
    "LLMUsage",
    "LiteLLMClient",
    "get_llm_client",
    "redact",
    "set_llm_client",
]
