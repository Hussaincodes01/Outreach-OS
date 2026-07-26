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


class LlmSettingsOut(ApiModel):
    # LiteLLM `provider/model`. None means "use the server default".
    default_llm_model: str | None = None
    available_models: list[str] = Field(default_factory=list)


class LlmSettingsIn(ApiModel):
    default_llm_model: str | None = Field(
        default=None,
        max_length=200,
        description="LiteLLM provider/model, e.g. 'openai/gpt-4o-mini'. Null resets to the default.",
    )


__all__ = [
    "LlmSettingsIn",
    "LlmSettingsOut",
    "OnboardingDismissIn",
    "OnboardingStatusOut",
    "OnboardingStepOut",
]
