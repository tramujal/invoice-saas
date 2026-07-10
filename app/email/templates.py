"""Invoice email content.

Reuses the same invoice-number formatting, status labels, and currency/
language resolution the PDF uses, so the email and the PDF can never drift
out of sync with each other.
"""

from app.currency import format_amount, get_currency_code
from app.invoice_numbering import format_invoice_number
from app.localization import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_language,
    payment_status_label,
    t,
)
from app.models import Customer, Invoice
from app.payment_status import PaymentStatus


def build_invoice_email(invoice: Invoice, customer: Customer) -> tuple[str, str]:
    """Returns (subject, plain-text body) for an invoice email.

    language/currency_code come from the invoice itself (permanently
    pinned at creation), not the organization's current settings — see
    Invoice.currency_code / Invoice.language.
    """
    language = get_language(invoice)
    currency_code = get_currency_code(invoice)

    invoice_number = format_invoice_number(invoice.invoice_number)
    status_label = payment_status_label(language, PaymentStatus(invoice.payment_status))

    subject = t(language, "email_subject").format(invoice_number=invoice_number)
    body = (
        f"{t(language, 'email_greeting').format(name=customer.name)}\n"
        "\n"
        f"{t(language, 'email_intro')}\n"
        "\n"
        f"{t(language, 'email_invoice_number_label')}\n"
        f"{invoice_number}\n"
        "\n"
        f"{t(language, 'email_total_label')}\n"
        f"{format_amount(invoice.total, currency_code)}\n"
        "\n"
        f"{t(language, 'email_payment_status_label')}\n"
        f"{status_label}\n"
        "\n"
        f"{t(language, 'email_thanks')}"
    )
    return subject, body


def build_password_reset_email(
    reset_link: str, language: str = DEFAULT_LANGUAGE
) -> tuple[str, str]:
    """Returns (subject, plain-text body) for a password reset email.

    Unlike build_invoice_email, there's no Organization to resolve a
    language from — Users aren't members of an org yet at this point, and
    even if they were, a password reset is a personal action, not an
    organization one. Instead the caller passes the language the visitor
    had selected on the public forgot-password page (see
    ForgotPasswordRequest.language), and an unrecognized value falls back
    to English.
    """
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    subject = t(language, "password_reset_subject")
    body = (
        f"{t(language, 'password_reset_greeting')}\n"
        "\n"
        f"{t(language, 'password_reset_instructions')}\n"
        "\n"
        f"{t(language, 'password_reset_link_label')}\n"
        f"{reset_link}\n"
        "\n"
        f"{t(language, 'password_reset_expiry')}\n"
        "\n"
        f"{t(language, 'password_reset_ignore')}"
    )
    return subject, body


def build_verification_email(
    verification_link: str, language: str = DEFAULT_LANGUAGE
) -> tuple[str, str]:
    """Returns (subject, plain-text body) for an email verification email.

    Same shape as build_password_reset_email, for the same reason: there's
    no Organization to resolve a language from at register time beyond what
    the visitor selected on the public register form (see
    RegisterRequest.language), and an unrecognized value falls back to
    English.
    """
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    subject = t(language, "verification_subject")
    body = (
        f"{t(language, 'verification_greeting')}\n"
        "\n"
        f"{t(language, 'verification_instructions')}\n"
        "\n"
        f"{t(language, 'verification_link_label')}\n"
        f"{verification_link}\n"
        "\n"
        f"{t(language, 'verification_expiry')}\n"
        "\n"
        f"{t(language, 'verification_ignore')}"
    )
    return subject, body
