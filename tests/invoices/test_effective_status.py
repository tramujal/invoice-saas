"""app.effective_status is the single source of truth for pending/paid/
overdue -- pure unit tests, no DB/HTTP needed. The timezone test monkeypatches
app.org_time's clock to a fixed instant so the org-local-vs-UTC calendar-day
difference is deterministic rather than depending on when the suite runs."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import app.org_time as org_time_module
from app.effective_status import get_effective_payment_status
from app.org_time import get_organization_today
from app.payment_status import PaymentStatus


def _invoice(payment_status: str, due_date: date | None) -> SimpleNamespace:
    return SimpleNamespace(payment_status=payment_status, due_date=due_date)


def test_paid_always_wins_regardless_of_due_date():
    today = date(2026, 1, 15)
    invoice = _invoice(PaymentStatus.paid.value, due_date=date(2026, 1, 1))
    assert get_effective_payment_status(invoice, today) == PaymentStatus.paid


def test_due_date_in_future_is_pending():
    today = date(2026, 1, 15)
    invoice = _invoice(PaymentStatus.pending.value, due_date=date(2026, 1, 20))
    assert get_effective_payment_status(invoice, today) == PaymentStatus.pending


def test_due_date_in_past_is_overdue():
    today = date(2026, 1, 15)
    invoice = _invoice(PaymentStatus.pending.value, due_date=date(2026, 1, 10))
    assert get_effective_payment_status(invoice, today) == PaymentStatus.overdue


def test_due_date_today_is_not_yet_overdue():
    today = date(2026, 1, 15)
    invoice = _invoice(PaymentStatus.pending.value, due_date=date(2026, 1, 15))
    assert get_effective_payment_status(invoice, today) == PaymentStatus.pending


def test_missing_due_date_falls_back_to_stored_status_unchanged():
    today = date(2026, 1, 15)
    invoice = _invoice(PaymentStatus.pending.value, due_date=None)
    assert get_effective_payment_status(invoice, today) == PaymentStatus.pending


def test_organization_timezone_shifts_which_calendar_day_is_today(monkeypatch):
    """23:30 UTC on Jan 15 is still Jan 15 in UTC, but already Jan 16 in a
    UTC+14 timezone -- the same invoice (due_date=Jan 15) must come out
    pending for a UTC org and overdue for a Kiritimati-timezone org, at
    the exact same real instant."""

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
            return fixed.astimezone(tz) if tz else fixed

    monkeypatch.setattr(org_time_module, "datetime", _FixedDatetime)

    utc_org = SimpleNamespace(timezone="UTC")
    kiritimati_org = SimpleNamespace(timezone="Pacific/Kiritimati")

    due_date = date(2026, 1, 15)
    invoice = _invoice(PaymentStatus.pending.value, due_date=due_date)

    utc_today = get_organization_today(utc_org)
    kiritimati_today = get_organization_today(kiritimati_org)
    assert utc_today != kiritimati_today

    assert get_effective_payment_status(invoice, utc_today) == PaymentStatus.pending
    assert get_effective_payment_status(invoice, kiritimati_today) == PaymentStatus.overdue
