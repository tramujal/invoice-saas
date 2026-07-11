import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.models import init_db
from app.routers import (
    assistant,
    assistant_actions,
    auth,
    customer_imports,
    customers,
    dashboard,
    insights,
    invoices,
    organizations,
)

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


app = FastAPI(title="Invoices API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(invoices.router)
app.include_router(customers.router)
app.include_router(customer_imports.router)
app.include_router(dashboard.router)
app.include_router(insights.router)
app.include_router(organizations.router)
app.include_router(assistant.router)
app.include_router(assistant_actions.router)
