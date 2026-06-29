"""LLM service — LiteLLM wrapper. Stub for Phase 0+1; full integration in Phase 3.

The dependency is included so that install + import work, but we do not
hit any LLM provider in Phase 0+1. The `complete` method here raises so
that any accidental use during the early phases is loud and obvious.
"""
from __future__ import annotations

from typing import Any


class LLMService:
    """Thin wrapper around litellm. Lazy-imports so unit tests don't need the dep."""

    def __init__(self, *, model: str = "gpt-4o-mini", provider: str | None = None) -> None:
        self.model = model
        self.provider = provider

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> str:
        raise NotImplementedError(
            "LLMService.complete is a Phase 3 feature. "
            "Phase 0+1 does not make any LLM calls."
        )
