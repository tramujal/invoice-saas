from tests.factories import make_user


def test_login_succeeds_with_correct_credentials(client, db_session):
    make_user(db_session, email="login@example.com")

    response = client.post(
        "/auth/login", json={"email": "login@example.com", "password": "Correct-Horse-1"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_rejects_wrong_password(client, db_session):
    make_user(db_session, email="login2@example.com")

    response = client.post(
        "/auth/login", json={"email": "login2@example.com", "password": "Wrong-Password-1"}
    )
    assert response.status_code == 401


def test_login_rejects_unknown_email(client):
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "Correct-Horse-1"}
    )
    assert response.status_code == 401


def test_me_reflects_verification_state(client, db_session):
    make_user(db_session, email="verified@example.com", verified=True)
    make_user(db_session, email="unverified@example.com", verified=False)

    verified_login = client.post(
        "/auth/login", json={"email": "verified@example.com", "password": "Correct-Horse-1"}
    ).json()
    unverified_login = client.post(
        "/auth/login", json={"email": "unverified@example.com", "password": "Correct-Horse-1"}
    ).json()

    verified_me = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {verified_login['access_token']}"}
    )
    unverified_me = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {unverified_login['access_token']}"}
    )

    assert verified_me.json()["user"]["email_verified"] is True
    assert unverified_me.json()["user"]["email_verified"] is False


def test_me_rejects_missing_token(client):
    response = client.get("/auth/me")
    assert response.status_code == 401
