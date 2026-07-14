"""Root pytest fixtures.

The env vars below MUST be set before any `app.*` module is imported,
since app.database/app.security read them at import time. This keeps the
whole suite off the real dev database and off the real JWT secret.
"""

import os
import tempfile

_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="saas_test_")
os.close(_TEST_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-used-in-production"
os.environ["ENVIRONMENT"] = "development"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import init_db  # noqa: E402
import app.rate_limit as rate_limit_module  # noqa: E402

# pysqlite (the stdlib sqlite3 driver) does its own implicit transaction
# handling that fights with SQLAlchemy's SAVEPOINT-based test-isolation
# recipe below. This is SQLAlchemy's documented workaround: let pysqlite
# do no transaction management of its own, and have SQLAlchemy emit BEGIN
# explicitly. See "Serializable isolation / Savepoints / Transactional
# DDL" in the SQLAlchemy SQLite dialect docs. Scoped to this engine only
# (the test engine), not app/database.py, since it's purely a test concern.


@event.listens_for(engine, "connect")
def _sqlite_disable_pysqlite_autocommit_quirk(dbapi_connection, _connection_record):
    dbapi_connection.isolation_level = None


@event.listens_for(engine, "begin")
def _sqlite_emit_begin(conn):
    conn.exec_driver_sql("BEGIN")


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    init_db()
    yield
    engine.dispose()
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


@pytest.fixture()
def db_session():
    """A DB session bound to a SAVEPOINT that's rolled back after the test.

    Service-layer code under test calls session.commit() directly and
    often. A plain "wrap in one transaction, roll back at the end"
    approach breaks the moment app code commits, since that ends the
    outer transaction early. `join_transaction_mode="create_savepoint"`
    (SQLAlchemy 2.0) binds the session to a single connection/outer
    transaction and transparently keeps it inside a SAVEPOINT no matter
    how many times app code calls commit(), so the whole thing can still
    be rolled back wholesale at teardown.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit_module._backend = rate_limit_module.InMemoryRateLimiterBackend()
    yield


@pytest.fixture(autouse=True)
def fake_email_sender(monkeypatch):
    """Patches every confirmed get_email_sender call site (plain function
    calls, not Depends() -- app.dependency_overrides has no effect on
    them) so no test can ever reach the real Resend API. Tests that care
    about sent mail read `.sent` off the returned fake."""
    from tests.fakes import FakeEmailSender

    sender = FakeEmailSender()
    monkeypatch.setattr("app.routers.auth.get_email_sender", lambda: sender)
    monkeypatch.setattr("app.routers.invitations.get_email_sender", lambda: sender)
    monkeypatch.setattr("app.routers.invitation_public.get_email_sender", lambda: sender)
    monkeypatch.setattr("app.services.invoices.get_email_sender", lambda: sender)
    monkeypatch.setattr("app.services.quotes.get_email_sender", lambda: sender)
    return sender


@pytest.fixture(autouse=True)
def fake_ai_provider(monkeypatch):
    """Patches both confirmed get_ai_provider call sites, same rationale
    as fake_email_sender above -- a developer's ambient shell may well
    have a real ANTHROPIC_API_KEY/GEMINI_API_KEY set, so clearing env
    vars alone wouldn't be enough; the call sites themselves must be
    replaced. Tests configure `.events`/`.error` on the returned fake
    before exercising the code under test."""
    from tests.fakes import FakeAIProvider

    provider = FakeAIProvider()
    monkeypatch.setattr("app.routers.assistant.get_ai_provider", lambda *a, **kw: provider)
    monkeypatch.setattr("app.insights.narration.get_ai_provider", lambda *a, **kw: provider)
    return provider
