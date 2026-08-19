"""Phase 25 -- localized notifications/emails.

Covers: the user -> organization -> platform-default language resolution
chain (app.localization.resolve_recipient_language), that
app.notifications.copy has no hardcoded English left (every event type
renders correctly in both "en" and "es"), and that
app.notifications.service.emit_event renders each active member's
Notification row in THAT MEMBER's own resolved language -- two members
of the same organization with different preferences get different text
for the exact same event, and the email job (which uses
Notification.title/body verbatim) inherits the same per-recipient
localization for free.
"""

import json

from app.localization import SUPPORTED_LANGUAGES, resolve_recipient_language, t
from app.models import BackgroundJob, Notification
from app.notifications.copy import render_notification_copy
from app.services.customers import create_customer_record
from app.webhook_event_type import WebhookEventType

from tests.factories import make_member_in_org, make_org_with_owner


# --- resolution chain -----------------------------------------------------


def test_resolve_recipient_language_prefers_user_language(db_session):
    owner = make_org_with_owner(db_session, email="lang-user@example.com")
    owner.user.language = "es"
    owner.organization.language = "en"
    db_session.commit()

    assert resolve_recipient_language(owner.user, owner.organization) == "es"


def test_resolve_recipient_language_falls_through_to_organization(db_session):
    owner = make_org_with_owner(db_session, email="lang-org@example.com")
    owner.user.language = None
    owner.organization.language = "es"
    db_session.commit()

    assert resolve_recipient_language(owner.user, owner.organization) == "es"


def test_resolve_recipient_language_falls_through_to_platform_default_when_both_missing(db_session):
    owner = make_org_with_owner(db_session, email="lang-default@example.com")
    owner.user.language = None
    owner.organization.language = "fr"  # unsupported -- get_language() itself defaults this to "en"
    db_session.commit()

    assert resolve_recipient_language(owner.user, owner.organization) == "en"


def test_resolve_recipient_language_ignores_unsupported_user_language(db_session):
    owner = make_org_with_owner(db_session, email="lang-bad@example.com")
    owner.user.language = "xx"  # not a supported language -- must not be trusted
    owner.organization.language = "es"
    db_session.commit()

    assert resolve_recipient_language(owner.user, owner.organization) == "es"


def test_resolve_recipient_language_handles_missing_user(db_session):
    owner = make_org_with_owner(db_session, email="lang-noone@example.com")
    owner.organization.language = "es"
    db_session.commit()

    assert resolve_recipient_language(None, owner.organization) == "es"


# --- copy.py has no hardcoded English: every event type, both languages --


_NOTE_PAYLOAD = {
    "note_number": "CN-000001",
    "note_type": "credit",
    "total": "300.00",
    "currency_code": "UYU",
}


def test_every_event_type_has_a_dedicated_renderer_in_both_languages():
    payload_by_type = {
        WebhookEventType.customer_created: {"name": "Acme"},
        WebhookEventType.customer_updated: {"name": "Acme"},
        WebhookEventType.customer_deleted: {"name": "Acme"},
        WebhookEventType.product_created: {"name": "Widget"},
        WebhookEventType.product_updated: {"name": "Widget"},
        WebhookEventType.product_archived: {"name": "Widget"},
        WebhookEventType.product_restored: {"name": "Widget"},
        WebhookEventType.quote_created: {"quote_number": "QUO-1"},
        WebhookEventType.quote_updated: {"quote_number": "QUO-1"},
        WebhookEventType.quote_deleted: {"quote_number": "QUO-1"},
        WebhookEventType.quote_sent: {"quote_number": "QUO-1", "customer_name": "Acme"},
        WebhookEventType.quote_accepted: {"quote_number": "QUO-1"},
        WebhookEventType.quote_rejected: {"quote_number": "QUO-1"},
        WebhookEventType.quote_converted: {"quote_number": "QUO-1"},
        WebhookEventType.invoice_created: {"invoice_number": "INV-1"},
        WebhookEventType.invoice_updated: {"invoice_number": "INV-1"},
        WebhookEventType.invoice_sent: {"invoice_number": "INV-1", "customer_name": "Acme"},
        # Phase 29 -- one payload shape serves all four note events; the
        # renderers differ only in which sentence they choose.
        WebhookEventType.adjustment_note_created: _NOTE_PAYLOAD,
        WebhookEventType.adjustment_note_issued: _NOTE_PAYLOAD,
        WebhookEventType.adjustment_note_voided: _NOTE_PAYLOAD,
        WebhookEventType.adjustment_note_sent: _NOTE_PAYLOAD,
        WebhookEventType.organization_plan_changed: {"new_plan": {"code": "pro"}},
        WebhookEventType.financial_insight_requested: {"report_id": "x"},
        WebhookEventType.financial_insight_generated: {"report_id": "x"},
        WebhookEventType.financial_insight_failed: {"report_id": "x", "error_code": "provider_error"},
    }
    assert set(payload_by_type) == set(WebhookEventType)  # every member covered by this test

    for event_type, payload in payload_by_type.items():
        seen_by_language = {}
        for language in SUPPORTED_LANGUAGES:
            title, body = render_notification_copy(event_type, payload, language)
            assert title and body
            # No stray, unformatted "{placeholder}" left in the output --
            # would indicate a .format() key mismatch against the payload.
            assert "{" not in title and "}" not in title
            assert "{" not in body and "}" not in body
            seen_by_language[language] = (title, body)
        # EN and ES must actually differ -- a renderer that silently fell
        # back to English for "es" would pass every other assertion above.
        assert seen_by_language["en"] != seen_by_language["es"]


def test_render_notification_copy_never_hardcodes_english_for_defaults():
    # Every "default"/fallback label (no name on file, no customer name,
    # unknown plan, ...) must also be translated -- not just the
    # surrounding sentence.
    title, body = render_notification_copy(WebhookEventType.customer_created, {}, "es")
    assert "Un cliente" in body
    assert "A customer" not in body


# --- end-to-end: emit_event renders PER RECIPIENT --------------------------


def test_two_members_with_different_languages_get_different_notification_text(db_session):
    owner = make_org_with_owner(db_session, email="multi-lang-owner@example.com")
    owner.user.language = "es"
    member = make_member_in_org(db_session, owner.organization, email="multi-lang-member@example.com")
    member.user.language = "en"
    db_session.commit()

    create_customer_record(
        db_session, owner.organization.id, name="Acme", email="a@example.com", phone="", address="", tax_id=""
    )

    owner_notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()
    member_notification = db_session.query(Notification).filter_by(user_id=member.user.id).one()

    assert owner_notification.title == "Cliente creado"
    assert "Acme" in owner_notification.body
    assert member_notification.title == "Customer created"
    assert "Acme" in member_notification.body
    assert owner_notification.title != member_notification.title


def test_member_without_a_personal_language_falls_through_to_organization_language(db_session):
    owner = make_org_with_owner(db_session, email="fallback-owner@example.com")
    owner.user.language = None
    owner.organization.language = "es"
    db_session.commit()

    create_customer_record(
        db_session, owner.organization.id, name="Beta", email="b@example.com", phone="", address="", tax_id=""
    )

    notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()
    assert notification.title == "Cliente creado"


def test_email_job_payload_uses_the_same_localized_notification_verbatim(db_session):
    owner = make_org_with_owner(db_session, email="email-lang-owner@example.com")
    owner.user.language = "es"
    db_session.commit()

    create_customer_record(
        db_session, owner.organization.id, name="Gamma", email="g@example.com", phone="", address="", tax_id=""
    )

    notification = db_session.query(Notification).filter_by(user_id=owner.user.id).one()
    job = db_session.query(BackgroundJob).filter_by(job_type="notification.email").one()
    assert json.loads(job.payload)["notification_id"] == notification.id
    assert notification.title == "Cliente creado"  # the email subject will be this exact, already-localized string
