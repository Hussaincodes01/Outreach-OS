"""Application configuration via pydantic-settings.

Reads from environment / .env. All settings are validated at import time.
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core ---
    environment: Literal["development", "staging", "production", "ci", "test"] = "development"
    log_level: str = "INFO"
    sentry_dsn: SecretStr | None = None

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://outreach:outreach@localhost:5433/outreach",
        description="Async SQLAlchemy URL for the main app database.",
    )
    database_url_sync: str = Field(
        default="postgresql://outreach:outreach@localhost:5433/outreach",
        description="Sync URL (used by Alembic via async driver compatibility shim).",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 5

    # --- CORS ---
    # Browser origins allowed to call the API. Accepts a comma-separated list
    # (e.g. "https://app.example.com,https://admin.example.com") or a JSON
    # array. In development/test, localhost origins are added automatically.
    # REQUIRED in production/staging — without it the deployed web app cannot
    # make authenticated cross-origin requests to the API.
    # `NoDecode` is essential, not cosmetic: without it pydantic-settings runs
    # json.loads() on the raw env value inside EnvSettingsSource — BEFORE any
    # field validator — so the documented comma-separated form raised
    # SettingsError and the API could not boot in production at all.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6380/0"
    celery_broker_url: str = "redis://localhost:6380/1"
    celery_result_backend: str = "redis://localhost:6380/2"

    # --- Vault ---
    # 32-byte Fernet key, base64-encoded. Generate with `openssl rand -base64 32`.
    vault_master_key: SecretStr = Field(default=SecretStr(""))

    # --- S3 ---
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_bucket: str = "outreach"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_region: str = "us-east-1"

    # --- SMTP (transactional, e.g. magic-link login) ---
    # Transactional SMTP (password resets, verification, digests). Empty host
    # means "no mail configured": the mailer falls back to logging instead of
    # failing every send against a server that isn't there. Deliberately NOT
    # defaulted to localhost — that would make the test suite open sockets and
    # would hide a misconfigured deployment behind connection errors.
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_use_tls: bool = False
    # From address on platform email. Must be a domain you control, or resets
    # land in spam.
    transactional_from_email: str = "no-reply@outreach-os.local"
    # Public URL of the WEB app (not the API). Reset and verification links
    # point here, so it has to be where the user's browser can reach the UI.
    web_base_url: str = "http://localhost:3000"

    # --- Phase 2: Lead scraping ---
    # Per-tenant, per-source rate limits (requests per minute). Source names
    # not listed here fall back to defaults in `core.rate_limit.DEFAULT_LIMITS`.
    scraping_rate_limits_per_minute: dict[str, int] = Field(default_factory=dict)
    # HTTP timeouts (seconds) for outbound scraping calls.
    scraping_http_timeout: float = 20.0
    # Maximum seconds a single scraping_job may run before being marked failed.
    scraping_job_timeout: int = 600
    # Fallback to StealthyFetcher (headless browser) when Fetcher gets blocked.
    scraping_use_stealth_fallback: bool = True
    # NOTE: a `scraping_robots_obey` flag used to live here, documented as
    # "Respect robots.txt Disallow/Crawl-delay directives". Nothing read it, so
    # it promised a compliance guarantee the scraper never enforced. Removed
    # rather than left in place — an operator seeing it default to True would
    # reasonably believe robots.txt was honoured. Tracked on the roadmap.
    # Fetch the lead's website during agent research for live context.
    scraping_live_research_enabled: bool = True
    scraping_live_research_max_chars: int = 600
    # Celery — when true, tasks run synchronously inside the calling process
    # (used by tests; do not enable in production).
    celery_task_always_eager: bool = False

    # --- Phase 3: LangGraph agent ---
    # Default LLM model in LiteLLM format, e.g. "openai/gpt-4o-mini" or
    # "anthropic/claude-3-5-sonnet-20240620". The campaign row can override.
    llm_default_model: str = "openai/gpt-4o-mini"
    # Embedding model in LiteLLM format. Default 1536-dim (text-embedding-3-small).
    llm_embedding_model: str = "openai/text-embedding-3-small"
    llm_embedding_dimensions: int = 1536
    # Max tokens per completion for the draft node.
    llm_draft_max_tokens: int = 800
    # Max tokens for niche/style classification nodes (short structured output).
    llm_classify_max_tokens: int = 300
    # Timeout (seconds) for any single LLM call.
    llm_request_timeout: int = 60
    # Chunk size (tokens) for RAG case-study splitting.
    rag_chunk_tokens: int = 400
    rag_chunk_overlap_tokens: int = 60
    # Top-k chunks retrieved per draft.
    rag_top_k: int = 4
    # Minimum similarity score (cosine, 0..1) for a chunk to be included.
    rag_min_similarity: float = 0.65
    # Max seconds a single draft-generation run may take before timing out.
    agent_run_timeout: int = 180
    # --- Tool-calling research agent ---
    # Master switch. Off falls back to the deterministic research step.
    agent_tools_enabled: bool = True
    # Hard cap on tool-calling rounds per draft. Each round is a completion the
    # tenant pays for on their own key, so this is a cost control, not a
    # performance tweak.
    agent_max_tool_steps: int = 6
    # Cumulative token budget for the research loop (excludes the draft call).
    agent_max_research_tokens: int = 12000
    # Default presigned-URL TTL (seconds) for draft S3 links.
    s3_presign_ttl: int = 900
    # Convenience bucket for drafts (separate from the general S3 bucket).
    s3_drafts_bucket: str = "outreach-drafts"

    # --- Phase 4: send + reply + follow-up ---
    # Default send window. 7am-7pm local; we don't have a timezone per
    # lead yet, so we use the server's local time. Per-tenant override
    # is a future concern.
    send_window_start_hour: int = 7
    send_window_end_hour: int = 19
    # Per-send jitter (in seconds) — added on top of scheduled_at to avoid
    # bursts. 0 means no jitter.
    send_jitter_seconds: int = 60
    # Cap per mailbox per local day. Mailbox.daily_send_cap overrides this.
    default_daily_send_cap: int = 50
    # How many sends a single send_due Celery pass may fire (rate limiter).
    send_batch_size: int = 25
    # Reply classifier LLM temperature (low — we want deterministic labels).
    reply_classify_temperature: float = 0.0
    # How many seconds to wait between follow-up steps by default.
    default_step_delay_days: int = 3
    # Celery beat interval (seconds) for the send_due + follow_up_due tasks.
    send_due_interval_seconds: int = 60
    follow_up_due_interval_seconds: int = 60
    # Stop the sequence after this many classification types.
    stop_on_replies: tuple[str, ...] = ("positive", "negative", "unsubscribe", "bounce")
    # Public base URL for tracking pixels and unsubscribe links.
    public_base_url: str = "http://localhost:8000"
    # Disclosure line appended to every outbound email (CAN-SPAM, GDPR).
    email_disclosure: str = (
        "This email was sent by Outreach OS on behalf of the sender. "
        "If you'd rather not hear from us, click unsubscribe."
    )
    # Inbound webhook shared secret (HMAC-SHA256 over the body).
    # MUST be set in production .env (no default for security).
    inbound_webhook_secret: str = ""
    # Per-IP rate limits (per minute) for public endpoints, e.g. {"webhook": 100}.
    auth_rate_limits_per_minute: dict[str, int] = Field(default_factory=dict)

    # --- Phase 5: meeting booking + CRM sync ---
    # Default meeting duration in minutes when creating proposals.
    meeting_default_duration_minutes: int = 30
    # Slot 1 time-of-day (UTC) used when generating the 3 default slots.
    meeting_default_slot_hour_utc: int = 10
    # How many working-day slots to propose (master plan: 3).
    meeting_proposed_slot_count: int = 3
    # Supported CRM providers in V1.
    crm_supported_providers: tuple[str, ...] = ("google_sheets",)

    # --- Phase 6: notifications ---
    # Master list of all event keys the notification system can emit.
    # Adding a new one is just appending to this tuple (and the UI
    # auto-discovers the key from /v1/notifications/events).
    notification_event_keys: tuple[str, ...] = (
        "reply.positive",
        "reply.negative",
        "reply.unsubscribe",
        "reply.bounce",
        "meeting.proposed",
        "meeting.confirmed",
        "meeting.declined",
        "meeting.cancelled",
        "send.failed",
        "send.bounced",
        "campaign.error",
        "scraping.completed",
        "scraping.failed",
        "crm.sync.failed",
    )
    # Default channels when a tenant has no NotificationPreference row yet.
    # Always allow in-app; everything else is opt-in.
    notification_default_channel_in_app: bool = True
    notification_default_channel_email_digest: bool = False
    notification_default_channel_slack: bool = False
    # Cron interval (seconds) for the daily email digest Celery beat.
    notification_email_digest_interval_seconds: int = 60
    # Stub Slack delivery latency in tests.
    notification_slack_request_timeout: int = 5

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string or a JSON array.

        The field is marked `NoDecode`, so this validator owns BOTH forms —
        pydantic-settings no longer pre-parses the value. Comma-separated is
        what `.env.production.example` documents and what operators actually
        write; the JSON array form is kept for backwards compatibility.
        """
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"CORS_ALLOWED_ORIGINS looks like JSON but is not valid: {exc}"
                ) from exc
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> Settings:
        """Fail fast at startup if a production/staging deployment is running
        with insecure development defaults. Catching this at boot is far safer
        than discovering it after the service is live."""
        if self.environment not in ("production", "staging"):
            return self

        problems: list[str] = []

        vault = self.vault_master_key.get_secret_value()
        if not vault:
            problems.append("VAULT_MASTER_KEY must be set (base64 Fernet key)")
        else:
            try:
                if len(base64.urlsafe_b64decode(vault)) < 32:
                    problems.append("VAULT_MASTER_KEY must decode to at least 32 bytes")
            except Exception:
                problems.append("VAULT_MASTER_KEY must be valid base64")

        if not self.inbound_webhook_secret:
            problems.append("INBOUND_WEBHOOK_SECRET must be set (HMAC secret for inbound replies)")

        if not self.cors_allowed_origins:
            problems.append("CORS_ALLOWED_ORIGINS must list the web app origin(s)")

        if self.celery_task_always_eager:
            problems.append("CELERY_TASK_ALWAYS_EAGER must be false in production")

        if self.public_base_url.startswith("http://localhost"):
            problems.append("PUBLIC_BASE_URL must be the public URL (tracking/unsubscribe links)")

        if problems:
            bullet = "\n  - "
            raise ValueError(
                f"Insecure or incomplete configuration for ENVIRONMENT={self.environment}:"
                + bullet
                + bullet.join(problems)
            )
        return self


# Helper alias for the schema layer (so the OpenAPI doc is clean).
NotificationEventKey = str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
