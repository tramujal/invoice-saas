"""claim_and_send_reminder's unique-constraint-based idempotency, plus
send_manual_invoice_reminder's gating -- exercised via the actual service
functions (never a re-implementation of the claim logic), using
FakeEmailSender so no real send ever happens."""

from datetime import date, timedelta

import pytest

from app.payment_status import PaymentStatus
from app.reminder_type import ReminderType
from app.services.invoices import (
    CustomerEmailMissingError,
    InvoiceAlreadyPaidError,
    InvoiceDueDateMissingError,
    RemindersDisabledError,
    ReminderAlreadySentError,
    ReminderSendFailedError,
    claim_and_send_reminder,
    send_manual_invoice_reminder,
)
from tests.factories import make_customer, make_invoice, make_org_with_owner


def _due_soon_invoice(db_session, owner, **kwargs):
    customer = kwargs.pop("customer", None) or make_customer(
        db_session, owner.organization, email="payer@example.com"
    )
    due_date = kwargs.pop("due_date", date.today() + timedelta(days=3))
    return make_invoice(db_session, owner.organization, owner.user, customer=customer, due_date=due_date)


def test_claim_and_send_reminder_succeeds_and_records_row(db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner@example.com")
    invoice = _due_soon_invoice(db_session, owner)

    claim_and_send_reminder(
        db_session,
        organization=owner.organization,
        invoice=invoice,
        reminder_type=ReminderType.before_due,
        days_offset=3,
        scheduled_for_date=date.today(),
        triggered_by="scheduled",
    )
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "payer@example.com"


def test_second_claim_for_same_slot_raises_already_sent(db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner2@example.com")
    invoice = _due_soon_invoice(db_session, owner)
    scheduled_for = date.today()

    claim_and_send_reminder(
        db_session,
        organization=owner.organization,
        invoice=invoice,
        reminder_type=ReminderType.before_due,
        days_offset=3,
        scheduled_for_date=scheduled_for,
        triggered_by="scheduled",
    )
    with pytest.raises(ReminderAlreadySentError):
        claim_and_send_reminder(
            db_session,
            organization=owner.organization,
            invoice=invoice,
            reminder_type=ReminderType.before_due,
            days_offset=3,
            scheduled_for_date=scheduled_for,
            triggered_by="scheduled",
        )
    # Only the first attempt actually sent anything.
    assert len(fake_email_sender.sent) == 1


def test_claim_for_different_reminder_type_same_day_is_independent(db_session, fake_email_sender):
    """The unique slot is (invoice_id, reminder_type, scheduled_for_date)
    -- a before_due and a due_today reminder for the same invoice on the
    same calendar day must both be claimable independently."""
    owner = make_org_with_owner(db_session, email="owner3@example.com")
    invoice = _due_soon_invoice(db_session, owner)
    scheduled_for = date.today()

    claim_and_send_reminder(
        db_session,
        organization=owner.organization,
        invoice=invoice,
        reminder_type=ReminderType.before_due,
        days_offset=3,
        scheduled_for_date=scheduled_for,
        triggered_by="scheduled",
    )
    claim_and_send_reminder(
        db_session,
        organization=owner.organization,
        invoice=invoice,
        reminder_type=ReminderType.due_today,
        days_offset=0,
        scheduled_for_date=scheduled_for,
        triggered_by="scheduled",
    )
    assert len(fake_email_sender.sent) == 2


def test_claim_skips_already_paid_invoice(db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner4@example.com")
    invoice = _due_soon_invoice(db_session, owner)
    invoice.payment_status = PaymentStatus.paid.value
    db_session.commit()

    with pytest.raises(InvoiceAlreadyPaidError):
        claim_and_send_reminder(
            db_session,
            organization=owner.organization,
            invoice=invoice,
            reminder_type=ReminderType.before_due,
            days_offset=3,
            scheduled_for_date=date.today(),
            triggered_by="scheduled",
        )
    assert fake_email_sender.sent == []


def test_claim_skips_invoice_without_due_date(db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner5@example.com")
    customer = make_customer(db_session, owner.organization, email="payer5@example.com")
    invoice = make_invoice(db_session, owner.organization, owner.user, customer=customer, due_date=None)

    with pytest.raises(InvoiceDueDateMissingError):
        claim_and_send_reminder(
            db_session,
            organization=owner.organization,
            invoice=invoice,
            reminder_type=ReminderType.due_today,
            days_offset=0,
            scheduled_for_date=date.today(),
            triggered_by="scheduled",
        )
    assert fake_email_sender.sent == []


def test_claim_skips_customer_without_email(db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner6@example.com")
    customer = make_customer(db_session, owner.organization, email="")
    invoice = make_invoice(
        db_session, owner.organization, owner.user, customer=customer, due_date=date.today()
    )

    with pytest.raises(CustomerEmailMissingError):
        claim_and_send_reminder(
            db_session,
            organization=owner.organization,
            invoice=invoice,
            reminder_type=ReminderType.due_today,
            days_offset=0,
            scheduled_for_date=date.today(),
            triggered_by="scheduled",
        )
    assert fake_email_sender.sent == []


def test_one_failed_send_does_not_affect_a_second_independent_reminder(db_session, fake_email_sender):
    """A provider failure on one reminder must never corrupt state for
    (or block) a completely independent reminder send right after it."""
    owner = make_org_with_owner(db_session, email="owner7@example.com")
    invoice_a = _due_soon_invoice(db_session, owner, customer=make_customer(
        db_session, owner.organization, email="a@example.com"
    ))
    invoice_b = _due_soon_invoice(db_session, owner, customer=make_customer(
        db_session, owner.organization, email="b@example.com"
    ))

    fake_email_sender.fail_next_n = 1
    with pytest.raises(ReminderSendFailedError):
        claim_and_send_reminder(
            db_session,
            organization=owner.organization,
            invoice=invoice_a,
            reminder_type=ReminderType.before_due,
            days_offset=3,
            scheduled_for_date=date.today(),
            triggered_by="scheduled",
        )

    claim_and_send_reminder(
        db_session,
        organization=owner.organization,
        invoice=invoice_b,
        reminder_type=ReminderType.before_due,
        days_offset=3,
        scheduled_for_date=date.today(),
        triggered_by="scheduled",
    )
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "b@example.com"


def test_manual_reminder_requires_reminders_enabled(db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner8@example.com")
    assert owner.organization.reminders_enabled is False
    invoice = _due_soon_invoice(db_session, owner)

    with pytest.raises(RemindersDisabledError):
        send_manual_invoice_reminder(
            db_session, owner.organization.id, invoice, triggered_by="manual"
        )
    assert fake_email_sender.sent == []


def test_manual_reminder_succeeds_once_reminders_enabled(db_session, fake_email_sender):
    owner = make_org_with_owner(db_session, email="owner9@example.com")
    owner.organization.reminders_enabled = True
    db_session.commit()
    invoice = _due_soon_invoice(db_session, owner)

    send_manual_invoice_reminder(db_session, owner.organization.id, invoice, triggered_by="manual")
    assert len(fake_email_sender.sent) == 1
