import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware

import app.jobs.bootstrap  # noqa: F401 -- populates the background-job registry
from app.database import get_db
from app.models import init_db
from app.request_metrics import record_request
from app.security_headers import apply_security_headers
from app.routers import (
    analytics,
    api_key_management,
    assistant,
    assistant_actions,
    audit,
    auth,
    billing,
    billing_webhooks,
    customer_imports,
    customers,
    dashboard,
    financial_intelligence,
    insights,
    invitation_public,
    invitations,
    invoices,
    notifications,
    organizations,
    platform_admin,
    product_imports,
    products,
    public_config,
    quote_public,
    quotes,
    team,
    webhooks,
    whatsapp,
    whatsapp_bridge,
)
from app.routers.api_v1 import customers as api_v1_customers
from app.routers.api_v1 import invoices as api_v1_invoices
from app.routers.api_v1 import products as api_v1_products
from app.routers.api_v1 import quotes as api_v1_quotes

# Without this, the root logger has no handler at all: WARNING+ messages
# only reach the console via Python's undocumented `logging.lastResort`
# fallback, and INFO messages are silently dropped everywhere in the app.
# This is the actual reason application-level logging (e.g. around the
# Resend API call) wasn't showing up in Render's log stream — configuring
# it here makes every `logging.getLogger(__name__)` call in the codebase
# actually emit to stdout/stderr, which Render captures.
#
# LOG_LEVEL (env, default "INFO") — lets an operator turn verbosity up
# (DEBUG, while chasing a production incident) or down (WARNING, to cut
# log volume/cost) without a code change or redeploy of a different
# image. An invalid value falls back to INFO rather than raising, since a
# typo here should never prevent the app from starting.
_LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
_LOG_LEVEL = logging.getLevelNamesMapping().get(_LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
_PRODUCTION_ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").strip().lower() == "production"


def _api_docs_enabled() -> bool:
    """Whether to serve the interactive API docs (/docs, /redoc) and the
    raw /openapi.json schema.

    Defaults to ENABLED outside production (a local developer should
    always get the docs with no configuration) and DISABLED in production
    -- the schema enumerates every route in the app, including every
    /admin platform-administration endpoint, which is reconnaissance
    material an anonymous visitor has no need for. Nothing behind those
    routes becomes reachable either way (every one re-checks auth on its
    own), so this is defense in depth, not an access control.

    API_DOCS_ENABLED=true re-enables them in production, deliberately:
    this app ships a documented PUBLIC REST API under /api/v1 for
    third-party integrations, and an operator who wants to publish those
    docs at their own domain should be able to, as an explicit,
    informed choice rather than an accident of the default."""
    raw = os.environ.get("API_DOCS_ENABLED", "").strip().lower()
    if raw in {"true", "1", "yes"}:
        return True
    if raw in {"false", "0", "no"}:
        return False
    return not _PRODUCTION_ENVIRONMENT


def _cors_origins() -> list[str]:
    """Reads CORS_ALLOWED_ORIGINS (comma-separated) from the environment.

    Falls back to the local frontend dev origins when unset, so local
    development needs no configuration. In production, set this to the
    deployed frontend URL(s) (e.g. the Vercel domain).

    Deliberately a warning, not a hard failure like app.security's own
    JWT_SECRET_KEY check, when ENVIRONMENT=production and this is unset:
    the practical effect of leaving it unset in production is that the
    real frontend origin silently can't call the API (every request
    fails CORS in the browser, immediately visible in any manual check
    or smoke test) — annoying but self-evident and non-destructive,
    unlike an insecure JWT secret, which fails silently and open. See
    docs/deployment.md's own environment-variable checklist."""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins:
        if _PRODUCTION_ENVIRONMENT:
            logging.getLogger(__name__).warning(
                "CORS_ALLOWED_ORIGINS is not set while ENVIRONMENT=production -- "
                "falling back to local dev origins (%s), which will reject every "
                "real browser request from the deployed frontend. Set "
                "CORS_ALLOWED_ORIGINS to the deployed frontend's URL(s).",
                ", ".join(_DEFAULT_CORS_ORIGINS),
            )
        return _DEFAULT_CORS_ORIGINS
    return origins


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


_DOCS_ENABLED = _api_docs_enabled()

app = FastAPI(
    title="Invoices API",
    version="1.0.0",
    lifespan=lifespan,
    # None disables the route entirely (FastAPI's own documented
    # mechanism) -- see _api_docs_enabled above for the default.
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
    description=(
        "The browser-facing application API is unversioned and requires a "
        "logged-in session. The **public REST API** for third-party "
        "integrations lives under `/api/v1` and is authenticated with an "
        "**Organization API Key** instead (`Authorization: Bearer sk_...`, "
        "see Settings → API Keys) -- see the `Public API — *` tags below."
    ),
    openapi_tags=[
        {
            "name": "Public API — Customers",
            "description": "Organization API Key authenticated. Requires the "
            "`customers.read`/`customers.write` key permission.",
        },
        {
            "name": "Public API — Products",
            "description": "Organization API Key authenticated. Requires the "
            "`products.read`/`products.write` key permission.",
        },
        {
            "name": "Public API — Quotes",
            "description": "Organization API Key authenticated. Requires the "
            "`quotes.read`/`quotes.write` key permission.",
        },
        {
            "name": "Public API — Invoices",
            "description": "Organization API Key authenticated. Requires the "
            "`invoices.read`/`invoices.write` key permission.",
        },
        {
            "name": "webhooks",
            "description": "Browser-session authenticated (Settings → Webhooks). "
            "Configures outbound webhook endpoints that receive a signed HTTP "
            "POST (see the `X-Webhook-Signature` header) whenever a subscribed "
            "event occurs -- at-least-once delivery, never exactly-once.",
        },
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _record_request_metrics(request: Request, call_next):
    """Feeds app.request_metrics -- see that module's own docstring for
    why this is an in-memory rolling window, not a persisted table.
    Registered before CORSMiddleware runs (Starlette applies middleware
    in reverse registration order, outermost-added-last), so timing
    includes the full request/response cycle seen by a real client."""
    started_at = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - started_at) * 1000
    record_request(duration_ms=duration_ms, is_error=response.status_code >= 500)
    return response


@app.middleware("http")
async def _add_security_headers(request: Request, call_next):
    response = await call_next(request)
    apply_security_headers(response)
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness only -- process is up and serving requests. Never touches
    the database, so it can't report unhealthy just because the DB is
    briefly unreachable (that's what /health/ready is for) -- a
    container orchestrator restarting this process wouldn't fix a DB
    outage anyway."""
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness -- process is up AND its database connection actually
    works. Distinguishes "the app is running" from "the app can serve a
    real request", the same liveness/readiness split Kubernetes (and any
    other orchestrator with the same two probe types) expects. A cheap,
    side-effect-free SELECT 1, not a real table query -- this only needs
    to prove the connection/credentials/network path works, not that any
    particular table exists yet.

    503, not 200-with-an-error-body, on failure -- an orchestrator's
    readiness probe checks the HTTP status code, not the response body;
    returning 200 here regardless of outcome would make this endpoint
    useless as an actual readiness gate."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logging.getLogger(__name__).error("health_ready: database check failed: %s", exc)
        raise HTTPException(status_code=503, detail={"status": "unavailable", "reason": "database"}) from exc
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(invoices.router)
app.include_router(customers.router)
app.include_router(customer_imports.router)
app.include_router(products.router)
app.include_router(product_imports.router)
app.include_router(quotes.router)
app.include_router(quote_public.router)
app.include_router(team.router)
app.include_router(invitations.router)
app.include_router(invitation_public.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(financial_intelligence.router)
app.include_router(billing.router)
app.include_router(billing_webhooks.router)
app.include_router(notifications.router)
app.include_router(insights.router)
app.include_router(organizations.router)
app.include_router(assistant.router)
app.include_router(assistant_actions.router)
app.include_router(platform_admin.router)
app.include_router(public_config.router)
app.include_router(api_key_management.router)
app.include_router(webhooks.router)
app.include_router(audit.router)
app.include_router(whatsapp.router)
app.include_router(whatsapp_bridge.router)
app.include_router(api_v1_customers.router)
app.include_router(api_v1_products.router)
app.include_router(api_v1_quotes.router)
app.include_router(api_v1_invoices.router)
