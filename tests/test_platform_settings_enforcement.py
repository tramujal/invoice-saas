"""Phase 13G -- the shared ai_enabled/emails_enabled enforcement points in
app.ai.factory.get_ai_provider and app.email.factory.get_email_sender.

Deliberately unit-level, not through the HTTP client: both functions
self-manage their own short-lived SessionLocal() (see each module's own
docstring), a separate connection from whatever the test's own db_session
fixture holds -- see app.services.platform_settings's docstring on why a
second self-managed connection can't observe an uncommitted SAVEPOINT the
test's session is holding. Patching get_effective_settings directly at
each factory module's import site exercises the exact real enforcement
branch (order of checks, exact exception raised) without any of that
cross-connection visibility risk, and proves the provider is never
constructed by making sure it *would* otherwise succeed (real, valid env
vars) if the disabled-check hadn't short-circuited first.
"""

import pytest
from fastapi import HTTPException

from app.services.platform_settings import SettingsSnapshot


def _snapshot(**overrides) -> SettingsSnapshot:
    defaults = dict(
        maintenance_mode=False,
        registrations_enabled=True,
        ai_enabled=True,
        emails_enabled=True,
        invoice_reminders_enabled=True,
        quote_reminders_enabled=True,
        default_language="en",
        default_currency="USD",
    )
    defaults.update(overrides)
    return SettingsSnapshot(**defaults)


def test_get_ai_provider_raises_ai_disabled_even_when_fully_configured(monkeypatch):
    from app.ai import factory as ai_factory

    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-but-present")
    monkeypatch.setenv("AI_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(ai_factory, "get_effective_settings", lambda *a, **kw: _snapshot(ai_enabled=False))

    def _should_never_construct(*args, **kwargs):
        raise AssertionError("AnthropicProvider must never be constructed while ai_enabled is False")

    monkeypatch.setattr(ai_factory, "AnthropicProvider", _should_never_construct)

    with pytest.raises(HTTPException) as exc_info:
        ai_factory.get_ai_provider()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "ai_disabled"


def test_get_ai_provider_succeeds_when_enabled_and_configured(monkeypatch):
    from app.ai import factory as ai_factory

    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-but-present")
    monkeypatch.setenv("AI_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(ai_factory, "get_effective_settings", lambda *a, **kw: _snapshot(ai_enabled=True))

    sentinel = object()
    monkeypatch.setattr(ai_factory, "AnthropicProvider", lambda **kwargs: sentinel)

    assert ai_factory.get_ai_provider() is sentinel


def test_get_email_sender_raises_emails_disabled_even_when_fully_configured(monkeypatch):
    from app.email import factory as email_factory

    monkeypatch.setenv("RESEND_API_KEY", "re_fake_but_present")
    monkeypatch.setenv("EMAIL_FROM", "test@example.com")
    monkeypatch.setattr(
        email_factory, "get_effective_settings", lambda *a, **kw: _snapshot(emails_enabled=False)
    )

    def _should_never_construct(*args, **kwargs):
        raise AssertionError("ResendEmailSender must never be constructed while emails_enabled is False")

    monkeypatch.setattr(email_factory, "ResendEmailSender", _should_never_construct)

    with pytest.raises(HTTPException) as exc_info:
        email_factory.get_email_sender()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "emails_disabled"


def test_get_email_sender_succeeds_when_enabled_and_configured(monkeypatch):
    from app.email import factory as email_factory

    monkeypatch.setenv("RESEND_API_KEY", "re_fake_but_present")
    monkeypatch.setenv("EMAIL_FROM", "test@example.com")
    monkeypatch.setattr(
        email_factory, "get_effective_settings", lambda *a, **kw: _snapshot(emails_enabled=True)
    )

    sentinel = object()
    monkeypatch.setattr(email_factory, "ResendEmailSender", lambda **kwargs: sentinel)

    assert email_factory.get_email_sender() is sentinel
