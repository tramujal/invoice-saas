"""Every /admin/* response must be safe to hand to a platform operator --
no password hashes, token hashes, or provider secret VALUES, ever. See
test_system_health_and_settings.py for the settings-specific proof that
real-looking secret values placed in the environment never leak; this
file sweeps every endpoint generically for the field-name-level leaks."""

import json

from tests.factories import make_customer, make_invoice, make_org_with_owner

_FORBIDDEN_SUBSTRINGS = ["hashed_password", "token_hash", "password", "api_key", "secret"]


def test_no_admin_endpoint_response_contains_secret_fields(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")
    customer = make_customer(db_session, owner.organization)
    make_invoice(db_session, owner.organization, owner.user, customer=customer)

    endpoints = [
        "/admin/dashboard",
        "/admin/organizations",
        f"/admin/organizations/{owner.organization.id}",
        "/admin/users",
        f"/admin/users/{owner.user.id}",
        "/admin/system/health",
        "/admin/settings",
    ]
    for path in endpoints:
        response = client.get(path, headers=super_admin_headers)
        assert response.status_code == 200, f"{path} did not return 200"
        raw = json.dumps(response.json()).lower()
        for term in _FORBIDDEN_SUBSTRINGS:
            assert term not in raw, f"{path} response contains forbidden term {term!r}"
