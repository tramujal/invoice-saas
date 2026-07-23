"""Confirms both scheduled reminder jobs exclude suspended organizations
outright -- see the module docstrings in app/jobs/send_due_invoice_
reminders.py and send_expiring_quote_reminders.py for the documented
product decision (no reason to keep emailing a frozen tenant's
customers)."""

from datetime import date, timedelta

from app.jobs.send_due_invoice_reminders import run as run_invoice_reminders
from app.jobs.send_expiring_quote_reminders import run as run_quote_reminders
from app.organization_status import OrganizationStatus
from app.quote_status import QuoteStatus
from tests.factories import make_customer, make_invoice, make_org_with_owner, make_quote


def test_invoice_reminder_job_skips_suspended_organizations(db_session, fake_email_sender, monkeypatch):
    monkeypatch.setattr("app.jobs.send_due_invoice_reminders.SessionLocal", lambda: db_session)

    active = make_org_with_owner(db_session, email="active-owner@example.com", org_name="Active Org")
    active.organization.reminders_enabled = True
    active.organization.reminder_on_due_date = True
    suspended = make_org_with_owner(db_session, email="suspended-owner@example.com", org_name="Suspended Org")
    suspended.organization.reminders_enabled = True
    suspended.organization.reminder_on_due_date = True
    suspended.organization.status = OrganizationStatus.suspended.value
    db_session.commit()

    active_customer = make_customer(db_session, active.organization, email="active-payer@example.com")
    suspended_customer = make_customer(db_session, suspended.organization, email="suspended-payer@example.com")
    make_invoice(db_session, active.organization, active.user, customer=active_customer, due_date=date.today())
    make_invoice(
        db_session, suspended.organization, suspended.user, customer=suspended_customer, due_date=date.today()
    )

    sent = run_invoice_reminders(dry_run=False)

    assert sent == 1
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "active-payer@example.com"


def test_quote_reminder_job_skips_suspended_organizations(db_session, fake_email_sender, monkeypatch):
    monkeypatch.setattr("app.jobs.send_expiring_quote_reminders.SessionLocal", lambda: db_session)

    active = make_org_with_owner(db_session, email="active-owner2@example.com", org_name="Active Org 2")
    active.organization.quote_reminders_enabled = True
    active.organization.quote_reminder_before_expiry_days = "3"
    suspended = make_org_with_owner(db_session, email="suspended-owner2@example.com", org_name="Suspended Org 2")
    suspended.organization.quote_reminders_enabled = True
    suspended.organization.quote_reminder_before_expiry_days = "3"
    suspended.organization.status = OrganizationStatus.suspended.value
    db_session.commit()

    active_customer = make_customer(db_session, active.organization, email="active-client@example.com")
    suspended_customer = make_customer(db_session, suspended.organization, email="suspended-client@example.com")

    active_quote = make_quote(
        db_session, active.organization, active.user, customer=active_customer,
        expiry_date=date.today() + timedelta(days=3),
    )
    active_quote.status = QuoteStatus.sent.value
    suspended_quote = make_quote(
        db_session, suspended.organization, suspended.user, customer=suspended_customer,
        expiry_date=date.today() + timedelta(days=3),
    )
    suspended_quote.status = QuoteStatus.sent.value
    db_session.commit()

    sent = run_quote_reminders(dry_run=False)

    assert sent == 1
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "active-client@example.com"
