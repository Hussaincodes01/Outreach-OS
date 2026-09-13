"""FastAPI application entry point."""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeAlias

import sentry_sdk
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from outreach_os.api.v1 import (
    audit,
    campaigns,
    credentials,
    crm,
    drafts,
    gdpr,
    icps,
    knowledge,
    lead_sources,
    leads,
    mailboxes,
    meetings,
    notification_preferences,
    notifications,
    onboarding,
    proxies,
    replies,
    scraping_jobs,
    sends,
    sequences,
    slack_webhooks,
    suppressions,
    tenants,
    tracking,
)
from outreach_os.core.config import get_settings
from outreach_os.core.db import dispose_engine
from outreach_os.core.errors import (
    AuthError,
    ConflictError,
    MailError,
    NotFoundError,
    OAuthError,
    OutreachError,
    SetupRequiredError,
    ValidationError,
)
from outreach_os.core.logging import configure_logging, get_logger
from outreach_os.services.local_workspace import ensure_local_workspace

# Starlette's BaseHTTPMiddleware dispatch signature.
_CallNext: TypeAlias = Callable[[Request], Awaitable[Response]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    log = get_logger("outreach_os.startup")
    log.info(
        "starting",
        environment=settings.environment,
        database_host=settings.database_url.split("@")[-1],
    )
    try:
        await ensure_local_workspace()
    except Exception as exc:
        # Keep booting: /health must still answer while the DB is down, and
        # the workspace is created again on the first request.
        log.warning("local_workspace_bootstrap_failed", error=str(exc)[:200])
    if settings.sentry_dsn and settings.environment != "development":
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.environment,
            traces_sample_rate=0.1,
        )
    yield
    await dispose_engine()
    log.info("shutdown complete")


app = FastAPI(
    title="Outreach OS",
    version="0.1.0",
    description="Multi-tenant AI cold outreach SaaS — internal API.",
    lifespan=lifespan,
)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next: _CallNext) -> Response:
    response = await call_next(request)
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Referrer policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Permissions policy (disable features not needed)
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # HSTS (only in production with HTTPS)
    settings = get_settings()
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Request size limit middleware.
#
# JSON bodies stay small. Lead-list uploads are the one legitimate exception:
# a few thousand rows of CSV easily exceeds 1MB, and a bare 413 on a customer's
# first import is a terrible introduction to the product. The import endpoints
# enforce their own row and byte ceilings (see services.lead_import).
_DEFAULT_MAX_BODY = 1_000_000
_UPLOAD_MAX_BODY = 10_000_000
_UPLOAD_PATHS = ("/v1/leads/import",)


@app.middleware("http")
async def limit_body_size(request: Request, call_next: _CallNext) -> Response:
    content_length = request.headers.get("content-length")
    if content_length:
        limit = (
            _UPLOAD_MAX_BODY
            if request.url.path.startswith(_UPLOAD_PATHS)
            else _DEFAULT_MAX_BODY
        )
        if int(content_length) > limit:
            return Response("Payload too large", status_code=413)
    return await call_next(request)


# CORS — production/staging origins come from CORS_ALLOWED_ORIGINS (validated
# at startup to be non-empty). Development/test also allow the local web app.
_settings = get_settings()
_cors_origins = list(_settings.cors_allowed_origins)
if _settings.environment in {"development", "test"}:
    _cors_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        *_cors_origins,
    ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# --- error mapping ---


@app.exception_handler(OutreachError)
async def _handle_domain_error(request: Request, exc: OutreachError) -> JSONResponse:
    log = get_logger("outreach_os.error")
    log.warning("domain_error", error=str(exc), path=request.url.path)
    status_map = {
        NotFoundError: status.HTTP_404_NOT_FOUND,
        AuthError: status.HTTP_401_UNAUTHORIZED,
        ValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
        OAuthError: status.HTTP_503_SERVICE_UNAVAILABLE,
        MailError: status.HTTP_502_BAD_GATEWAY,
        ConflictError: status.HTTP_409_CONFLICT,
        # 428: the request was fine, the workspace just isn't configured yet.
        # The web app keys off this to route the user into onboarding.
        SetupRequiredError: status.HTTP_428_PRECONDITION_REQUIRED,
    }
    code = status_map.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=code, content={"detail": str(exc)})


# --- routes ---


app.include_router(tenants.router, prefix="/v1")
app.include_router(credentials.router, prefix="/v1")
app.include_router(onboarding.router, prefix="/v1")
app.include_router(mailboxes.router, prefix="/v1")
app.include_router(audit.router, prefix="/v1")
app.include_router(icps.router, prefix="/v1")
app.include_router(lead_sources.router, prefix="/v1")
app.include_router(leads.router, prefix="/v1")
app.include_router(scraping_jobs.router, prefix="/v1")
app.include_router(proxies.router, prefix="/v1")
app.include_router(campaigns.router, prefix="/v1")
app.include_router(knowledge.router, prefix="/v1")
app.include_router(drafts.router, prefix="/v1")
app.include_router(drafts.agent_router, prefix="/v1")
# Phase 4
app.include_router(sequences.router, prefix="/v1")
app.include_router(sends.router, prefix="/v1")
app.include_router(replies.router, prefix="/v1")
app.include_router(replies.webhook_router, prefix="/v1")
app.include_router(suppressions.router, prefix="/v1")
# Phase 5
app.include_router(meetings.router, prefix="/v1")
app.include_router(crm.router, prefix="/v1")
# Phase 6 — notifications (incl. WebSocket)
app.include_router(notifications.router, prefix="/v1")
app.include_router(notification_preferences.router, prefix="/v1")
app.include_router(slack_webhooks.router, prefix="/v1")
# GDPR
app.include_router(gdpr.router, prefix="/v1")
# Public tracking endpoints (no /v1 prefix)
app.include_router(tracking.router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    """Liveness + DB ping. Returns 200 if the DB is reachable."""
    from sqlalchemy import text

    from outreach_os.core.db import get_engine

    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)[:200]}
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": "Outreach OS API",
        "version": app.version,
        "docs": "/docs",
    }


__all__ = ["app"]
