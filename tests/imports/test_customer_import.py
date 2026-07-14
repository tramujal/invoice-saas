"""Customer CSV import -- exercised via real multipart uploads through
TestClient, using small in-memory byte strings (no committed fixture
files)."""

from tests.factories import make_customer, make_org_with_owner


def _upload(client, org_id, headers, content: bytes, endpoint="confirm", filename="customers.csv"):
    return client.post(
        f"/organizations/{org_id}/customers/import/{endpoint}",
        files={"file": (filename, content, "text/csv")},
        headers=headers,
    )


def test_preview_valid_csv(client, db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    csv_bytes = b"name,email\nAlice,alice@example.com\nBob,bob@example.com\n"

    response = _upload(client, owner.organization.id, owner.auth_headers, csv_bytes, endpoint="preview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_rows"] == 2
    assert body["valid_count"] == 2
    assert body["invalid_count"] == 0


def test_confirm_imports_valid_rows(client, db_session):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    csv_bytes = b"name,email\nAlice,alice2@example.com\nBob,bob2@example.com\n"

    response = _upload(client, owner.organization.id, owner.auth_headers, csv_bytes)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_count"] == 2
    assert body["failed_count"] == 0
    assert body["total_processed"] == 2


def test_confirm_missing_required_field_fails_that_row_only(client, db_session):
    """One row missing the required "name" field must fail on its own,
    without preventing the other, valid rows from being imported."""
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    csv_bytes = b"name,email\nAlice,alice3@example.com\n,noname@example.com\nCarol,carol3@example.com\n"

    response = _upload(client, owner.organization.id, owner.auth_headers, csv_bytes)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_count"] == 2
    assert body["failed_count"] == 1
    assert body["total_processed"] == 3


def test_confirm_duplicate_email_is_skipped_not_failed(client, db_session):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    make_customer(db_session, owner.organization, name="Existing", email="dup4@example.com")

    csv_bytes = b"name,email\nNew Person,dup4@example.com\n"
    response = _upload(client, owner.organization.id, owner.auth_headers, csv_bytes)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_count"] == 0
    assert body["skipped_duplicate_count"] == 1
    assert body["failed_count"] == 0


def test_confirm_duplicate_within_same_file_only_first_wins(client, db_session):
    owner = make_org_with_owner(db_session, email="owner5@example.com")
    csv_bytes = (
        b"name,email\n"
        b"First,samefile@example.com\n"
        b"Second,samefile@example.com\n"
    )
    response = _upload(client, owner.organization.id, owner.auth_headers, csv_bytes)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_count"] == 1
    assert body["skipped_duplicate_count"] == 1


def test_malformed_file_is_rejected(client, db_session):
    owner = make_org_with_owner(db_session, email="owner6@example.com")
    # Claims to be .xlsx but is not a real zip/xlsx archive.
    response = _upload(
        client, owner.organization.id, owner.auth_headers, b"not a real spreadsheet",
        filename="customers.xlsx",
    )
    assert response.status_code == 415


def test_empty_file_is_rejected(client, db_session):
    owner = make_org_with_owner(db_session, email="owner7@example.com")
    response = _upload(client, owner.organization.id, owner.auth_headers, b"")
    assert response.status_code == 400


def test_unsupported_extension_is_rejected(client, db_session):
    owner = make_org_with_owner(db_session, email="owner8@example.com")
    response = _upload(
        client, owner.organization.id, owner.auth_headers, b"hello world", filename="customers.txt"
    )
    assert response.status_code == 415


def test_import_confirm_never_persists_rows_from_invalid_rows(client, db_session):
    """Confirm never trusts a prior preview -- re-parsing an invalid file
    at confirm time must persist nothing at all."""
    from app.models import Customer

    owner = make_org_with_owner(db_session, email="owner9@example.com")
    csv_bytes = b"name,email\n,bademail\n"

    response = _upload(client, owner.organization.id, owner.auth_headers, csv_bytes)
    assert response.status_code == 200
    assert response.json()["imported_count"] == 0
    assert db_session.query(Customer).filter_by(organization_id=owner.organization.id).count() == 0


def test_viewer_cannot_import_customers(client, db_session):
    from app.membership_role import MembershipRole
    from tests.factories import make_member_in_org

    owner = make_org_with_owner(db_session, email="owner10@example.com")
    viewer = make_member_in_org(
        db_session, owner.organization, email="viewer@example.com", role=MembershipRole.viewer
    )
    csv_bytes = b"name,email\nAlice,alice10@example.com\n"
    response = _upload(client, owner.organization.id, viewer.auth_headers, csv_bytes)
    assert response.status_code == 403
