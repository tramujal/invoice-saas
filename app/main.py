import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware

import app.jobs.bootstrap  # noqa: F401 -- populates the background-job registry
from app.models import init_db
from app.request_metrics import record_request
from app.routers import (
    analytics,
    api_key_management,
    assistant,
    assistant_actions,
    auth,
    billing,
    billing_webhooks,
    customer_imports,
    customers,
    dashboard,
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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def _cors_origins() -> list[str]:
    """Reads CORS_ALLOWED_ORIGINS (comma-separated) from the environment.

    Falls back to the local frontend dev origins when unset, so local
    development needs no configuration. In production, set this to the
    deployed frontend URL(s) (e.g. the Vercel domain).
    """
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or _DEFAULT_CORS_ORIGINS


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Invoices API",
    version="1.0.0",
    lifespan=lifespan,
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


@app.get("/health")
def health() -> dict[str, str]:
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
app.include_router(api_v1_customers.router)
app.include_router(api_v1_products.router)
app.include_router(api_v1_quotes.router)
app.include_router(api_v1_invoices.router)
