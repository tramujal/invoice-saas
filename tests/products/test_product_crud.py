from tests.factories import make_org_with_owner, make_product


def test_create_product_via_api(client, db_session):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    response = client.post(
        f"/organizations/{owner.organization.id}/products",
        json={"name": "Consulting Hour", "default_unit_price": "75.00"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Consulting Hour"


def test_archive_and_restore_product(client, db_session):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    product = make_product(db_session, owner.organization)

    archived = client.post(
        f"/organizations/{owner.organization.id}/products/{product.id}/archive",
        headers=owner.auth_headers,
    )
    assert archived.status_code == 200
    assert archived.json()["active"] is False

    restored = client.post(
        f"/organizations/{owner.organization.id}/products/{product.id}/restore",
        headers=owner.auth_headers,
    )
    assert restored.status_code == 200
    assert restored.json()["active"] is True


def test_archived_product_excluded_by_active_filter(client, db_session):
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    product = make_product(db_session, owner.organization, name="Archived One")
    client.post(
        f"/organizations/{owner.organization.id}/products/{product.id}/archive",
        headers=owner.auth_headers,
    )

    response = client.get(
        f"/organizations/{owner.organization.id}/products",
        params={"active": "true"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert product.id not in ids


def test_update_product(client, db_session):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    product = make_product(db_session, owner.organization)

    response = client.patch(
        f"/organizations/{owner.organization.id}/products/{product.id}",
        json={"name": "Renamed"},
        headers=owner.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_viewer_cannot_create_product(client, db_session):
    from app.membership_role import MembershipRole
    from tests.factories import make_member_in_org

    owner = make_org_with_owner(db_session, email="owner5@example.com")
    viewer = make_member_in_org(
        db_session, owner.organization, email="viewer@example.com", role=MembershipRole.viewer
    )
    response = client.post(
        f"/organizations/{owner.organization.id}/products",
        json={"name": "Blocked Product"},
        headers=viewer.auth_headers,
    )
    assert response.status_code == 403
