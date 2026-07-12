"""Reminder email content -- sibling to app.email.templates, reusing its
exact conventions: language/currency_code always come from the invoice
itself (permanently pinned at creation), never the organization's current
settings, so a reminder email looks the same regardless of what the
organization's defaults have changed to since.
"""

from app.currency import format_amount, get_currency_code
from app.invoice_numbering import format_invoice_number
from app.localization import get_language, t
from app.models import Customer, Invoice


def build_before_due_reminder_email(
    invoice: Invoice, customer: Customer, days_remaining: int
) -> tuple[str, str]:
    language = get_language(invoice)
    currency_code = get_currency_code(invoice)
    invoice_number = format_invoice_number(invoice.invoice_number)

    subject = t(language, "reminder_before_due_subject").format(invoice_number=invoice_number)
    body = _build_body(
        language,
        invoice,
        customer,
        currency_code,
        invoice_number,
        greeting_key="reminder_before_due_greeting",
        intro_key="reminder_before_due_intro",
        intro_kwargs={"days": days_remaining},
    )
    return subject, body


def build_due_today_reminder_email(invoice: Invoice, customer: Customer) -> tuple[str, str]:
    language = get_language(invoice)
    currency_code = get_currency_code(invoice)
    invoice_number = format_invoice_number(invoice.invoice_number)

    subject = t(language, "reminder_due_today_subject").format(invoice_number=invoice_number)
    body = _build_body(
        language,
        invoice,
        customer,
        currency_code,
        invoice_number,
        greeting_key="reminder_due_today_greeting",
        intro_key="reminder_due_today_intro",
        intro_kwargs={},
    )
    return subject, body


def build_after_due_reminder_email(
    invoice: Invoice, customer: Customer, days_overdue: int
) -> tuple[str, str]:
    language = get_language(invoice)
    currency_code = get_currency_code(invoice)
    invoice_number = format_invoice_number(invoice.invoice_number)

    subject = t(language, "reminder_after_due_subject").format(invoice_number=invoice_number)
    body = _build_body(
        language,
        invoice,
        customer,
        currency_code,
        invoice_number,
        greeting_key="reminder_after_due_greeting",
        intro_key="reminder_after_due_intro",
        intro_kwargs={"days": days_overdue},
    )
    return subject, body


def _build_body(
    language: str,
    invoice: Invoice,
    customer: Customer,
    currency_code: str,
    invoice_number: str,
    *,
    greeting_key: str,
    intro_key: str,
    intro_kwargs: dict,
) -> str:
    due_date_text = invoice.due_date.strftime("%B %d, %Y") if invoice.due_date else "—"
    return (
        f"{t(language, greeting_key).format(name=customer.name)}\n"
        "\n"
        f"{t(language, intro_key).format(**intro_kwargs)}\n"
        "\n"
        f"{t(language, 'reminder_invoice_number_label')}\n"
        f"{invoice_number}\n"
        "\n"
        f"{t(language, 'reminder_due_date_label')}\n"
        f"{due_date_text}\n"
        "\n"
        f"{t(language, 'reminder_total_label')}\n"
        f"{format_amount(invoice.total, currency_code)}\n"
        "\n"
        f"{t(language, 'reminder_closing')}\n"
        "\n"
        f"{t(language, 'reminder_thanks')}"
    )
