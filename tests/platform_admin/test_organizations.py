from tests.factories import make_customer, make_invoice, make_org_with_owner, make_quote


def test_list_organizations_pagination(client, db_session, super_admin_headers):
    for i in range(3):
        make_org_with_owner(db_session, email=f"owner{i}@example.com", org_name=f"Org {i}")

    first_page = client.get("/admin/organizations?limit=2&offset=0", headers=super_admin_headers)
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert first_body["total"] == 3
    assert len(first_body["items"]) == 2

    second_page = client.get("/admin/organizations?limit=2&offset=2", headers=super_admin_headers)
    assert len(second_page.json()["items"]) == 1


def test_list_organizations_search_by_name(client, db_session, super_admin_headers):
    make_org_with_owner(db_session, email="a@example.com", org_name="Rivera Design Studio")
    make_org_with_owner(db_session, email="b@example.com", org_name="Bluepeak Architecture")

    response = client.get("/admin/organizations?search=rivera", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Rivera Design Studio"


def test_organization_summary_fields_are_correct(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")
    customer = make_customer(db_session, owner.organization)
    make_invoice(db_session, owner.organization, owner.user, customer=customer)
    make_invoice(db_session, owner.organization, owner.user, customer=customer)
    make_quote(db_session, owner.organization, owner.user, customer=customer)

    response = client.get("/admin/organizations", headers=super_admin_headers)

    assert response.status_code == 200
    org_row = next(o for o in response.json()["items"] if o["id"] == owner.organization.id)
    assert org_row["owner_email"] == "owner@example.com"
    assert org_row["members_count"] == 1
    assert org_row["invoices_count"] == 2
    assert org_row["quotes_count"] == 1
    assert org_row["customers_count"] == 1
    assert org_row["created_at"] is not None
    assert org_row["last_activity_at"] is not None


def test_get_organization_detail_not_found(client, super_admin_headers):
    response = client.get("/admin/organizations/does-not-exist", headers=super_admin_headers)

    assert response.status_code == 404


def test_get_organization_detail_includes_members_and_recent_documents(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")
    customer = make_customer(db_session, owner.organization)
    make_invoice(db_session, owner.organization, owner.user, customer=customer)

    response = client.get(f"/admin/organizations/{owner.organization.id}", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["members_count"] == 1
    assert len(body["members"]) == 1
    assert body["members"][0]["email"] == "owner@example.com"
    assert body["members"][0]["role"] == "owner"
    assert len(body["recent_documents"]) == 1
    assert body["recent_documents"][0]["type"] == "invoice"
    # A freshly created organization is always active (Phase 13D).
    assert body["status"] == "active"
