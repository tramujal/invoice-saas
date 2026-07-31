"""Customer CSV import -- exercised via real multipart uploads through
TestClient, using small in-memory byte strings (no committed fixture
files)."""

from contextlib import contextmanager

from sqlalchemy import event

from app.database import engine as app_engine
from tests.factories import make_customer, make_org_with_owner, make_org_with_owner_on_plan


@contextmanager
def _count_queries():
    """Counts every statement actually sent to the DB during the `with`
    block, engine-wide -- used to prove app.imports.customers' plan-limit
    check no longer re-resolves capabilities (1 entitlements + 8 usage-
    count queries, see app.billing.capabilities.get_organization_capabilities)
    on every single imported row (Phase P2.2, H2)."""
    count = 0

    def _on_execute(*_args, **_kwargs):
        nonlocal count
        count += 1

    event.listen(app_engine, "before_cursor_execute", _on_execute)
    try:
        yield lambda: count
    finally:
        event.remove(app_engine, "before_cursor_execute", _on_execute)


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


def test_import_stops_at_plan_limit_every_row_past_cap_fails(client, db_session):
    """Phase P2.2 (H2) regression: switching from a per-row check_limit()
    call to a once-per-import LimitTracker must not change WHAT gets
    enforced, only how many queries it costs. With a 2-customer cap and 4
    valid rows, exactly the first 2 must import and the last 2 must both
    fail with plan_limit_reached -- not just the first row past the cap,
    proving the tracker's local counter keeps raising on every
    subsequent row rather than only once."""
    owner = make_org_with_owner_on_plan(db_session, email="import-limit@example.com", max_customers=2)
    csv_bytes = (
        b"name,email\n"
        b"One,one@example.com\n"
        b"Two,two@example.com\n"
        b"Three,three@example.com\n"
        b"Four,four@example.com\n"
    )

    response = _upload(client, owner.organization.id, owner.auth_headers, csv_bytes)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported_count"] == 2
    assert body["failed_count"] == 2
    failed_rows = [row for row in body["row_results"] if row["status"] == "failed"]
    assert len(failed_rows) == 2
    assert all(row["reason_code"] == "plan_limit_reached" for row in failed_rows)

    from app.models import Customer

    assert db_session.query(Customer).filter_by(organization_id=owner.organization.id).count() == 2


def test_open_limit_tracker_resolves_capabilities_once_consume_costs_no_queries(db_session):
    """Phase P2.2 (H2), isolated at the exact layer the finding is about:
    open_limit_tracker() does real queries (the row lock + entitlements +
    8 usage counts -- see app.billing.capabilities
    .get_organization_capabilities), but every subsequent .consume() call
    must do ZERO queries, no matter how many rows are being imported.
    Asserted directly against app.services.plan_limits rather than
    through a full CSV upload, since an HTTP-level import's total query
    count is dominated by other, legitimately-per-row work (emit_event's
    own webhook/notification/audit fan-out for each created row) that
    this finding was never about and this phase doesn't touch."""
    from app.services.plan_limits import LimitedResource, open_limit_tracker

    owner = make_org_with_owner_on_plan(db_session, email="tracker-query-count@example.com", max_customers=100)
    db_session.commit()

    with _count_queries() as get_count:
        tracker = open_limit_tracker(db_session, owner.organization.id, LimitedResource.customers)
    resolve_queries = get_count()
    assert resolve_queries > 0

    with _count_queries() as get_count:
        for _ in range(25):
            tracker.consume()
    consume_queries = get_count()

    assert consume_queries == 0
    assert tracker.used == 25
