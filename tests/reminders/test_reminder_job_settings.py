"""Phase 13G -- global reminder kill switches (app.services.platform_settings)
and maintenance-mode override for both scheduled reminder jobs. Mirrors
test_reminder_job_suspension.py's SessionLocal-patching pattern: each job
opens its own session, so the test's own settings mutation must go
through that same patched session to be visible to the job."""

from datetime import date

from app.jobs.send_due_invoice_reminders import run as run_invoice_reminders
from app.jobs.send_expiring_quote_reminders import run as run_quote_reminders
from app.models import PLATFORM_SETTINGS_SINGLETON_ID, PlatformSettings
from app.quote_status import QuoteStatus
from tests.factories import make_customer, make_invoice, make_org_with_owner, make_quote


def _settings_row(db_session) -> PlatformSettings:
    row = db_session.get(PlatformSettings, PLATFORM_SETTINGS_SINGLETON_ID)
    assert row is not None, "conftest.py's session-scoped fixture should have seeded this row"
    return row


def test_invoice_reminder_job_skips_entire_run_during_maintenance_mode(
    db_session, fake_email_sender, monkeypatch
):
    monkeypatch.setattr("app.jobs.send_due_invoice_reminders.SessionLocal", lambda: db_session)

    owner = make_org_with_owner(db_session, email="owner@example.com", org_name="Acme")
    owner.organization.reminders_enabled = True
    owner.organization.reminder_on_due_date = True
    _settings_row(db_session).maintenance_mode = True
    db_session.commit()

    customer = make_customer(db_session, owner.organization, email="payer@example.com")
    make_invoice(db_session, owner.organization, owner.user, customer=customer, due_date=date.today())

    sent = run_invoice_reminders(dry_run=False)

    assert sent == 0
    assert len(fake_email_sender.sent) == 0


def test_invoice_reminder_job_skips_entire_run_when_globally_disabled(
    db_session, fake_email_sender, monkeypatch
):
    monkeypatch.setattr("app.jobs.send_due_invoice_reminders.SessionLocal", lambda: db_session)

    owner = make_org_with_owner(db_session, email="owner2@example.com", org_name="Acme 2")
    owner.organization.reminders_enabled = True
    owner.organization.reminder_on_due_date = True
    _settings_row(db_session).invoice_reminders_enabled = False
    db_session.commit()

    customer = make_customer(db_session, owner.organization, email="payer2@example.com")
    make_invoice(db_session, owner.organization, owner.user, customer=customer, due_date=date.today())

    sent = run_invoice_reminders(dry_run=False)

    assert sent == 0
    assert len(fake_email_sender.sent) == 0


def test_invoice_reminder_job_runs_when_globally_enabled_and_org_enabled(
    db_session, fake_email_sender, monkeypatch
):
    monkeypatch.setattr("app.jobs.send_due_invoice_reminders.SessionLocal", lambda: db_session)

    owner = make_org_with_owner(db_session, email="owner3@example.com", org_name="Acme 3")
    owner.organization.reminders_enabled = True
    owner.organization.reminder_on_due_date = True
    db_session.commit()

    customer = make_customer(db_session, owner.organization, email="payer3@example.com")
    make_invoice(db_session, owner.organization, owner.user, customer=customer, due_date=date.today())

    sent = run_invoice_reminders(dry_run=False)

    assert sent == 1
    assert len(fake_email_sender.sent) == 1


def test_quote_reminder_job_skips_entire_run_during_maintenance_mode(
    db_session, fake_email_sender, monkeypatch
):
    monkeypatch.setattr("app.jobs.send_expiring_quote_reminders.SessionLocal", lambda: db_session)

    owner = make_org_with_owner(db_session, email="owner4@example.com", org_name="Acme 4")
    owner.organization.quote_reminders_enabled = True
    owner.organization.quote_reminder_before_expiry_days = "3"
    _settings_row(db_session).maintenance_mode = True
    db_session.commit()

    customer = make_customer(db_session, owner.organization, email="client4@example.com")
    from datetime import timedelta

    quote = make_quote(
        db_session, owner.organization, owner.user, customer=customer,
        expiry_date=date.today() + timedelta(days=3),
    )
    quote.status = QuoteStatus.sent.value
    db_session.commit()

    sent = run_quote_reminders(dry_run=False)

    assert sent == 0
    assert len(fake_email_sender.sent) == 0


def test_quote_reminder_job_skips_entire_run_when_globally_disabled(
    db_session, fake_email_sender, monkeypatch
):
    monkeypatch.setattr("app.jobs.send_expiring_quote_reminders.SessionLocal", lambda: db_session)

    owner = make_org_with_owner(db_session, email="owner5@example.com", org_name="Acme 5")
    owner.organization.quote_reminders_enabled = True
    owner.organization.quote_reminder_before_expiry_days = "3"
    _settings_row(db_session).quote_reminders_enabled = False
    db_session.commit()

    customer = make_customer(db_session, owner.organization, email="client5@example.com")
    from datetime import timedelta

    quote = make_quote(
        db_session, owner.organization, owner.user, customer=customer,
        expiry_date=date.today() + timedelta(days=3),
    )
    quote.status = QuoteStatus.sent.value
    db_session.commit()

    sent = run_quote_reminders(dry_run=False)

    assert sent == 0
    assert len(fake_email_sender.sent) == 0
