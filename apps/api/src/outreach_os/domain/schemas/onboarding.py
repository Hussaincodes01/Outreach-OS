"""Onboarding + workspace LLM settings schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import Field

from outreach_os.domain.schemas.common import ApiModel


class OnboardingStepOut(ApiModel):
    key: str
    title: str
    description: str
    done: bool
    required: bool
    # Route the web app should link to for this step.
    href: str
    detail: str | None = None


class OnboardingStatusOut(ApiModel):
    # True once every *required* step is done, i.e. the workspace can actually
    # generate and send an email.
    ready: bool
    dismissed: bool
    completed_at: datetime | None = None
    next_step_key: str | None = None
    steps: list[OnboardingStepOut] = Field(default_factory=list)


class OnboardingDismissIn(ApiModel):
    dismissed: bool = True


class ModelOut(ApiModel):
    """A suggested model. Not a whitelist — any model on a connected
    provider is accepted, so newly released ones work immediately."""

    id: str
    label: str
    provider: str
    provider_label: str
    supports_tools: bool
    context_window: int
    tier: str
    # False when the tenant has no key for this model's provider.
    available: bool


class EmbeddingModelOut(ApiModel):
    id: str
    label: str
    provider: str
    provider_label: str
    dimensions: int
    available: bool


class LlmSettingsOut(ApiModel):
    # LiteLLM `provider/model`. None means "use the server default".
    default_llm_model: str | None = None
    embedding_llm_model: str | None = None
    # Flat id list, kept for backwards compatibility with older clients.
    available_models: list[str] = Field(default_factory=list)
    models: list[ModelOut] = Field(default_factory=list)
    embedding_models: list[EmbeddingModelOut] = Field(default_factory=list)


class LlmSettingsIn(ApiModel):
    default_llm_model: str | None = Field(
        default=None,
        max_length=200,
        description="LiteLLM provider/model, e.g. 'openai/gpt-4o-mini'. Null resets to the default.",
    )
    embedding_llm_model: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Embedding model for the knowledge base. Must produce 1536 "
            "dimensions. Null resets to the default."
        ),
    )


__all__ = [
    "EmbeddingModelOut",
    "LlmSettingsIn",
    "LlmSettingsOut",
    "ModelOut",
    "OnboardingDismissIn",
    "OnboardingStatusOut",
    "OnboardingStepOut",
]
