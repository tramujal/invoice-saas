from tests.factories import make_org_with_owner, make_user


def test_list_users_pagination(client, db_session, super_admin_headers):
    for i in range(3):
        make_user(db_session, email=f"user{i}@example.com")

    response = client.get("/admin/users?limit=2&offset=0", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4  # 3 seeded + the super_admin fixture's own user
    assert len(body["items"]) == 2


def test_list_users_search_by_email(client, db_session, super_admin_headers):
    make_user(db_session, email="findme@example.com")
    make_user(db_session, email="other@example.com")

    response = client.get("/admin/users?search=findme", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "findme@example.com"


def test_list_users_filter_by_platform_role(client, db_session, super_admin_headers, super_admin):
    make_user(db_session, email="ordinary@example.com")

    response = client.get("/admin/users?has_platform_role=true", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == super_admin.email
    assert body["items"][0]["platform_role"] == "super_admin"


def test_list_users_filter_by_email_verified(client, db_session, super_admin_headers):
    make_user(db_session, email="verified@example.com", verified=True)
    make_user(db_session, email="unverified@example.com", verified=False)

    response = client.get("/admin/users?email_verified=false", headers=super_admin_headers)

    assert response.status_code == 200
    emails = {item["email"] for item in response.json()["items"]}
    assert "unverified@example.com" in emails
    assert "verified@example.com" not in emails


def test_get_user_detail_not_found(client, super_admin_headers):
    response = client.get("/admin/users/does-not-exist", headers=super_admin_headers)

    assert response.status_code == 404


def test_get_user_detail_includes_organizations(client, db_session, super_admin_headers):
    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")

    response = client.get(f"/admin/users/{owner.user.id}", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["organization_name"] == "Acme"
    assert body["organizations"][0]["role"] == "owner"
    # Never exposed anywhere in this API.
    assert "hashed_password" not in body
    assert "last_login_at" not in body
