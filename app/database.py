import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def _normalize_database_url(url: str) -> str:
    """Rewrites bare postgres(ql):// URLs to explicitly use the psycopg3 driver.

    Many hosts (Render, Railway, Heroku-style platforms) hand out DATABASE_URL
    as ``postgres://...`` or ``postgresql://...`` with no driver specified,
    which historically meant psycopg2. This app installs psycopg3 instead, so
    we rewrite the scheme rather than requiring users to edit the platform's
    connection string by hand.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


DATABASE_URL = _normalize_database_url(
    os.environ.get("DATABASE_URL", "sqlite:///./invoices.db")
)

_is_sqlite = make_url(DATABASE_URL).get_backend_name() == "sqlite"

if _is_sqlite:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        # SQLite ignores ON DELETE CASCADE unless foreign keys are turned on
        # per-connection; Postgres always enforces them. Enabling this locally
        # keeps dev behavior consistent with production.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    # Tuned for a SERVERLESS/managed Postgres (Neon, Supabase, RDS Proxy),
    # which is what every documented deployment path for this app actually
    # uses -- see docs/deployment.md.
    #
    # pool_pre_ping: avoids errors from stale connections after a DB
    #   restart or network blip. Essential on Neon, which routinely closes
    #   idle connections from its own side (autosuspend); without this the
    #   first query after an idle period fails instead of transparently
    #   reconnecting.
    # pool_recycle: proactively discards a connection this app has held
    #   longer than the interval, so it is never the side that discovers a
    #   server-closed socket. 300s is comfortably under Neon's own idle
    #   timeout while still reusing connections for real traffic.
    # pool_size / max_overflow: bounded deliberately. SQLAlchemy's defaults
    #   (5 + 10) are PER PROCESS, and docker-compose.prod.yml runs uvicorn
    #   with WEB_CONCURRENCY workers plus a separate worker container --
    #   the defaults can therefore multiply into far more server-side
    #   connections than a small managed instance allows. These values are
    #   overridable per deployment without a code change.
    _pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
    _max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "5"))
    _pool_recycle = int(os.environ.get("DB_POOL_RECYCLE_SECONDS", "300"))
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=_pool_recycle,
        pool_size=_pool_size,
        max_overflow=_max_overflow,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
