def test_system_health_reports_unconfigured_providers(client, super_admin_headers, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)

    response = client.get("/admin/system/health", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["database_reachable"] is True
    assert body["email_provider_configured"] is False
    assert body["email_provider"] is None
    assert body["ai_provider_configured"] is False
    assert body["ai_provider"] is None
    assert body["reminder_emails_pending"] == 0
    assert body["reminder_emails_sent_7d"] == 0
    assert body["reminder_emails_failed_7d"] == 0


def test_system_health_reports_configured_email_provider(client, super_admin_headers, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key_not_real")
    monkeypatch.setenv("EMAIL_FROM", "test@example.com")

    response = client.get("/admin/system/health", headers=super_admin_headers)

    body = response.json()
    assert body["email_provider_configured"] is True
    assert body["email_provider"] == "resend"


def test_settings_reflects_effective_config_without_leaking_values(client, super_admin_headers, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_super_secret_value_12345")
    monkeypatch.setenv("EMAIL_FROM", "test@example.com")
    monkeypatch.setenv("GEMINI_API_KEY", "another_super_secret_value")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    response = client.get("/admin/settings", headers=super_admin_headers)

    assert response.status_code == 200
    raw = response.text
    assert "re_super_secret_value_12345" not in raw
    assert "another_super_secret_value" not in raw

    body = response.json()
    assert body["ai_provider"] == "gemini"
    assert body["email_provider"] == "resend"
    assert body["cors_allowed_origins"] == ["https://app.example.com"]


def test_settings_requires_settings_view_permission(client, db_session):
    from app.security import create_access_token
    from tests.factories import make_user

    user = make_user(db_session, email="not-an-admin@example.com")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    response = client.get("/admin/settings", headers=headers)

    assert response.status_code == 403


def test_settings_returns_deterministic_defaults_before_any_write(client, super_admin_headers):
    response = client.get("/admin/settings", headers=super_admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["maintenance_mode"] is False
    assert body["registrations_enabled"] is True
    assert body["ai_enabled"] is True
    assert body["emails_enabled"] is True
    assert body["invoice_reminders_enabled"] is True
    assert body["quote_reminders_enabled"] is True
    assert body["default_language"] == "en"
    assert body["default_currency"] == "USD"
    assert body["updated_by_email"] is None
    assert body["version"] == 1


def test_patch_settings_requires_settings_manage_permission(client, db_session):
    from app.security import create_access_token
    from tests.factories import make_user

    user = make_user(db_session, email="not-an-admin-2@example.com")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    response = client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "maintenance_mode": True},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_permission_denied"


def test_patch_settings_rejects_missing_reason(client, super_admin_headers):
    response = client.patch(
        "/admin/settings",
        json={"expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    assert response.status_code == 422


def test_patch_settings_rejects_missing_expected_version(client, super_admin_headers):
    response = client.patch(
        "/admin/settings", json={"reason": "test", "maintenance_mode": True}, headers=super_admin_headers
    )
    assert response.status_code == 422


def test_patch_settings_rejects_blank_reason(client, super_admin_headers):
    response = client.patch(
        "/admin/settings",
        json={"reason": "   ", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    assert response.status_code == 422


def test_patch_settings_rejects_empty_update_with_no_setting_fields(client, super_admin_headers):
    response = client.patch(
        "/admin/settings", json={"reason": "test", "expected_version": 1}, headers=super_admin_headers
    )
    assert response.status_code == 422


def test_patch_settings_rejects_invalid_language_and_currency(client, super_admin_headers):
    bad_language = client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "default_language": "xx"},
        headers=super_admin_headers,
    )
    assert bad_language.status_code == 422

    bad_currency = client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "default_currency": "ZZZ"},
        headers=super_admin_headers,
    )
    assert bad_currency.status_code == 422


def test_patch_settings_updates_single_field_and_returns_effective_settings(
    client, db_session, super_admin_headers, super_admin
):
    response = client.patch(
        "/admin/settings",
        json={"reason": "enabling maintenance for deploy", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["maintenance_mode"] is True
    # Untouched fields keep their prior values -- a genuine partial update.
    assert body["registrations_enabled"] is True
    assert body["updated_by_email"] == super_admin.email
    assert body["version"] == 2


def test_patch_settings_partial_update_only_changes_supplied_fields(client, super_admin_headers):
    client.patch(
        "/admin/settings",
        json={"reason": "first change", "expected_version": 1, "ai_enabled": False},
        headers=super_admin_headers,
    )

    response = client.patch(
        "/admin/settings",
        json={"reason": "second change", "expected_version": 2, "emails_enabled": False},
        headers=super_admin_headers,
    )

    body = response.json()
    assert body["ai_enabled"] is False
    assert body["emails_enabled"] is False
    assert body["version"] == 3


def test_patch_settings_no_op_returns_409_conflict(client, super_admin_headers):
    first = client.patch(
        "/admin/settings",
        json={"reason": "turn on maintenance", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    assert first.status_code == 200
    assert first.json()["version"] == 2

    second = client.patch(
        "/admin/settings",
        json={"reason": "same value again", "expected_version": 2, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "no_changes"

    # A no-op must never bump the version.
    current = client.get("/admin/settings", headers=super_admin_headers)
    assert current.json()["version"] == 2


def test_patch_settings_records_exactly_one_audit_row_with_changed_fields_only(
    client, db_session, super_admin_headers, super_admin
):
    from app.models import PlatformAuditLog

    response = client.patch(
        "/admin/settings",
        json={
            "reason": "quarterly currency default change",
            "expected_version": 1,
            "default_currency": "EUR",
            "registrations_enabled": False,
        },
        headers=super_admin_headers,
    )
    assert response.status_code == 200

    rows = db_session.query(PlatformAuditLog).filter_by(action="platform.settings_updated").all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_email == super_admin.email
    assert row.reason == "quarterly currency default change"
    assert row.target_organization_id is None
    assert row.target_user_id is None

    import json

    details = json.loads(row.details)
    assert set(details.keys()) == {
        "default_currency",
        "registrations_enabled",
        "old_version",
        "new_version",
    }
    assert details["default_currency"] == {"old": "USD", "new": "EUR"}
    assert details["registrations_enabled"] == {"old": True, "new": False}
    assert details["old_version"] == 1
    assert details["new_version"] == 2


def test_patch_settings_writes_no_audit_row_on_validation_failure_or_no_op(
    client, db_session, super_admin_headers
):
    from app.models import PlatformAuditLog

    client.patch(
        "/admin/settings", json={"reason": "test", "expected_version": 1}, headers=super_admin_headers
    )
    client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "default_language": "xx"},
        headers=super_admin_headers,
    )
    # A no-op after a real, already-applied change.
    client.patch(
        "/admin/settings",
        json={"reason": "first", "expected_version": 1, "maintenance_mode": True},
        headers=super_admin_headers,
    )
    client.patch(
        "/admin/settings",
        json={"reason": "duplicate", "expected_version": 2, "maintenance_mode": True},
        headers=super_admin_headers,
    )

    rows = db_session.query(PlatformAuditLog).filter_by(action="platform.settings_updated").all()
    assert len(rows) == 1


def test_patch_settings_never_leaks_configured_secrets(client, super_admin_headers, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_super_secret_patch_value")

    response = client.patch(
        "/admin/settings",
        json={"reason": "test", "expected_version": 1, "emails_enabled": False},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert "re_super_secret_patch_value" not in response.text


def test_settings_distinguishes_enabled_but_not_configured_from_configured(
    client, super_admin_headers, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)

    # ai_enabled stays true (the default) but no provider is configured --
    # a distinct state from "disabled," and the response must show it as
    # such (ai_provider null, ai_enabled still true).
    response = client.get("/admin/settings", headers=super_admin_headers)

    body = response.json()
    assert body["ai_enabled"] is True
    assert body["ai_provider"] is None
