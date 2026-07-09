"""Invoice email content.

Reuses the same invoice-number formatting and status labels the PDF uses, so
the email and the PDF can never drift out of sync with each other.
"""

from app.currency import get_currency_code
from app.invoice_numbering import format_invoice_number
from app.invoice_pdf import PAYMENT_STATUS_LABELS
from app.models import Customer, Invoice
from app.payment_status import PaymentStatus


def build_invoice_email(invoice: Invoice, customer: Customer) -> tuple[str, str]:
    """Returns (subject, plain-text body) for an invoice email."""
    invoice_number = format_invoice_number(invoice.invoice_number)
    status_label = PAYMENT_STATUS_LABELS.get(
        PaymentStatus(invoice.payment_status), invoice.payment_status
    )
    currency_code = get_currency_code()

    subject = f"Invoice {invoice_number}"
    body = (
        f"Hello {customer.name},\n"
        "\n"
        "Please find your invoice attached.\n"
        "\n"
        "Invoice Number:\n"
        f"{invoice_number}\n"
        "\n"
        "Total:\n"
        f"{currency_code} {invoice.total:.2f}\n"
        "\n"
        "Payment Status:\n"
        f"{status_label}\n"
        "\n"
        "Thank you."
    )
    return subject, body
