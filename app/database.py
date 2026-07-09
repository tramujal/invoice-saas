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
    # pool_pre_ping avoids errors from stale connections after a DB restart
    # or network blip, which matters once the database is a networked service.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
