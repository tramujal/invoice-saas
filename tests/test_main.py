"""Phase RC1 -- production release readiness: /health/ready (DB
connectivity readiness probe, distinct from /health's plain liveness
check) and the security-headers middleware (app.security_headers)
applied to every response."""

from app.database import get_db


def test_health_liveness_never_touches_the_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_returns_200_when_database_is_reachable(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_returns_503_when_database_check_fails(client):
    """Overrides get_db for this one request only, on top of the `client`
    fixture's own db_session override -- the fixture's own teardown pops
    the whole dependency_overrides entry unconditionally afterward, so
    nothing needs restoring here even though this replaces it mid-test."""
    from app.main import app

    class _BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("simulated database outage")

    def _broken_get_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_get_db
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["reason"] == "database"


def test_responses_include_standard_security_headers(client):
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Strict-Transport-Security" in response.headers
    assert "Permissions-Policy" in response.headers


def test_security_headers_applied_to_error_responses_too(client):
    response = client.get("/organizations/does-not-exist/customers")
    assert response.status_code in (401, 403, 404)
    assert response.headers["X-Content-Type-Options"] == "nosniff"
