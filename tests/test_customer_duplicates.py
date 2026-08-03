"""Phase UX5 -- tiered customer duplicate detection.

Covers app.customer_duplicates (unit-level), the check-duplicates
endpoint, tax-id blocking enforced server-side in create/update, historical
duplicate preservation, and normalization.
"""

import json

import pytest

from app.customer_duplicates import DuplicateSeverity, check_customer_duplicates
from app.models import AuditEntry
from tests.factories import make_customer, make_org_with_owner


def _check(client, org_id, headers, **body):
    return client.post(f"/organizations/{org_id}/customers/check-duplicates", json=body, headers=headers)


# --- Unit-level: app.customer_duplicates -----------------------------------


def test_tax_id_match_is_blocking(db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", tax_id="12.345.678-9")

    result = check_customer_duplicates(
        db_session, owner.organization.id, tax_id="123456789"
    )
    assert result.severity == DuplicateSeverity.blocking
    assert result.matches[0].reasons == ["tax_id"]


def test_email_match_is_warning(db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", email="Billing@Acme.com")

    result = check_customer_duplicates(
        db_session, owner.organization.id, email="billing@acme.com  ".strip()
    )
    assert result.severity == DuplicateSeverity.warning
    assert "email" in result.matches[0].reasons


def test_phone_match_is_warning(db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", phone="+598 99-123-456")

    result = check_customer_duplicates(
        db_session, owner.organization.id, phone="+598 99 123 456"
    )
    assert result.severity == DuplicateSeverity.warning
    assert "phone" in result.matches[0].reasons


def test_name_only_match_is_suggestion_never_blocks(db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="  Juan   Perez ")

    result = check_customer_duplicates(db_session, owner.organization.id, name="juan perez")
    assert result.severity == DuplicateSeverity.suggestion
    assert result.matches[0].reasons == ["name"]


def test_no_match_is_none(db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", email="a@acme.com")

    result = check_customer_duplicates(db_session, owner.organization.id, email="nobody@nowhere.com")
    assert result.severity == DuplicateSeverity.none
    assert result.matches == []


def test_different_organization_never_matches(db_session):
    owner_a = make_org_with_owner(db_session, email="a@example.com", org_name="Org A")
    owner_b = make_org_with_owner(db_session, email="b@example.com", org_name="Org B")
    make_customer(db_session, owner_a.organization, name="Acme", tax_id="123456789")

    result = check_customer_duplicates(db_session, owner_b.organization.id, tax_id="123456789")
    assert result.severity == DuplicateSeverity.none


def test_exclude_customer_id_never_matches_itself(db_session):
    owner = make_org_with_owner(db_session)
    customer = make_customer(db_session, owner.organization, name="Acme", tax_id="123456789")

    result = check_customer_duplicates(
        db_session,
        owner.organization.id,
        tax_id="123456789",
        exclude_customer_id=customer.id,
    )
    assert result.severity == DuplicateSeverity.none


def test_empty_field_means_skip_that_field(db_session):
    """The edit flow relies on this: an unchanged field is sent blank so
    it never re-surfaces a warning about a collision the user isn't
    touching."""
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", email="billing@acme.com")

    result = check_customer_duplicates(db_session, owner.organization.id, email="")
    assert result.severity == DuplicateSeverity.none


def test_multiple_reasons_on_one_match_take_highest_severity(db_session):
    owner = make_org_with_owner(db_session)
    make_customer(
        db_session,
        owner.organization,
        name="Acme",
        email="billing@acme.com",
        tax_id="123456789",
    )

    result = check_customer_duplicates(
        db_session, owner.organization.id, email="billing@acme.com", tax_id="123456789"
    )
    assert result.severity == DuplicateSeverity.blocking
    assert set(result.matches[0].reasons) == {"email", "tax_id"}


# --- HTTP endpoint -----------------------------------------------------------


def test_check_duplicates_endpoint_returns_warning(client, db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", email="billing@acme.com")

    response = _check(client, owner.organization.id, owner.auth_headers, email="billing@acme.com")
    assert response.status_code == 200
    body = response.json()
    assert body["severity"] == "warning"
    assert body["matches"][0]["reasons"] == ["email"]


def test_check_duplicates_requires_permission(client, db_session):
    owner = make_org_with_owner(db_session, email="a@example.com", org_name="Org A")
    other = make_org_with_owner(db_session, email="b@example.com", org_name="Org B")

    response = _check(client, owner.organization.id, other.auth_headers, email="x@example.com")
    assert response.status_code == 403


def test_check_duplicates_requires_auth(client, db_session):
    owner = make_org_with_owner(db_session)
    response = client.post(
        f"/organizations/{owner.organization.id}/customers/check-duplicates", json={}
    )
    assert response.status_code == 401


# --- Server-side tax-id blocking (create/update) -----------------------------


def test_create_customer_blocks_on_duplicate_tax_id(client, db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", tax_id="12.345.678-9")

    response = client.post(
        f"/organizations/{owner.organization.id}/customers",
        json={"name": "Acme 2", "email": "acme2@example.com", "tax_id": "123456789"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "duplicate_tax_id"
    assert "already belongs to another customer" in detail["message"]
    assert "customer_id" in detail


def test_create_customer_never_blocks_on_duplicate_email(client, db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", email="shared@acme.com")

    response = client.post(
        f"/organizations/{owner.organization.id}/customers",
        json={
            "name": "Acme Branch",
            "email": "shared@acme.com",
            "duplicate_warning_acknowledged": True,
        },
        headers=owner.auth_headers,
    )
    assert response.status_code == 201


def test_create_customer_records_duplicate_warning_acknowledged_in_audit(client, db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", email="shared@acme.com")

    response = client.post(
        f"/organizations/{owner.organization.id}/customers",
        json={
            "name": "Acme Branch",
            "email": "shared@acme.com",
            "duplicate_warning_acknowledged": True,
        },
        headers=owner.auth_headers,
    )
    assert response.status_code == 201
    new_id = response.json()["id"]

    entry = db_session.query(AuditEntry).filter_by(resource_id=new_id).one()
    payload = json.loads(entry.metadata_json)
    assert payload["duplicate_warning_acknowledged"] is True


def test_update_customer_blocks_on_duplicate_tax_id(client, db_session):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme", tax_id="123456789")
    other = make_customer(db_session, owner.organization, name="Beta", email="beta@example.com")

    response = client.patch(
        f"/organizations/{owner.organization.id}/customers/{other.id}",
        json={"tax_id": "12.345.678-9"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_tax_id"


def test_update_customer_does_not_block_on_its_own_unchanged_tax_id(client, db_session):
    owner = make_org_with_owner(db_session)
    customer = make_customer(db_session, owner.organization, name="Acme", tax_id="123456789")

    response = client.patch(
        f"/organizations/{owner.organization.id}/customers/{customer.id}",
        json={"name": "Acme Renamed", "tax_id": "123456789"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Acme Renamed"


# --- Historical duplicates never break --------------------------------------


def test_historical_duplicate_tax_ids_are_preserved_and_still_listed(client, db_session):
    """Simulates pre-existing data drift: two customers already share a
    tax_id (created directly, bypassing the new check, exactly like data
    that existed before this feature shipped). The feature must never
    touch, hide, or break these rows -- only block a NEW third one."""
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="Acme A", tax_id="123456789")
    make_customer(db_session, owner.organization, name="Acme B", tax_id="12.345.678-9")

    listing = client.get(
        f"/organizations/{owner.organization.id}/customers", headers=owner.auth_headers
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 2

    blocked = client.post(
        f"/organizations/{owner.organization.id}/customers",
        json={"name": "Acme C", "email": "c@example.com", "tax_id": "123-456-789"},
        headers=owner.auth_headers,
    )
    assert blocked.status_code == 409


@pytest.mark.parametrize(("raw_a", "raw_b"), [("12.345.678-9", "123456789"), ("12 345 678 9", "123456789")])
def test_tax_id_normalization_treats_formatted_variants_as_equal(db_session, raw_a, raw_b):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="X", tax_id=raw_a)
    result = check_customer_duplicates(db_session, owner.organization.id, tax_id=raw_b)
    assert result.severity == DuplicateSeverity.blocking


@pytest.mark.parametrize(
    ("raw_a", "raw_b"),
    [("+598 (99) 123-456", "+598 99 123 456"), ("0059899123456", "+598 99 123 456")],
)
def test_phone_normalization_treats_formatted_variants_as_equal(db_session, raw_a, raw_b):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name="X", phone=raw_a)
    result = check_customer_duplicates(db_session, owner.organization.id, phone=raw_b)
    assert result.severity == DuplicateSeverity.warning


@pytest.mark.parametrize(("raw_a", "raw_b"), [("  Juan   Perez  ", "juan perez"), ("JUAN PEREZ", "juan perez")])
def test_name_normalization_treats_formatted_variants_as_equal(db_session, raw_a, raw_b):
    owner = make_org_with_owner(db_session)
    make_customer(db_session, owner.organization, name=raw_a)
    result = check_customer_duplicates(db_session, owner.organization.id, name=raw_b)
    assert result.severity == DuplicateSeverity.suggestion
