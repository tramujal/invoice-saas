"""Quote email content.

Mirrors app.email.templates.build_invoice_email's exact conventions
(currency/language pinned on the quote itself, never the organization's
current settings) -- reuses the same currency formatting and localization
helpers, plus the accept/reject public links this feature adds.
"""

from app.currency import format_amount, get_currency_code
from app.localization import get_language, quote_status_label, t
from app.models import Customer, Quote
from app.quote_numbering import format_quote_number


def build_quote_email(
    quote: Quote, customer: Customer, accept_link: str, reject_link: str
) -> tuple[str, str]:
    """Returns (subject, plain-text body) for a "Send Quote" email."""
    language = get_language(quote)
    currency_code = get_currency_code(quote)

    quote_number = format_quote_number(quote.quote_number)
    status_label = quote_status_label(language, quote.effective_status)
    expiry_line = (
        f"{t(language, 'quote_email_expiry_date_label')}\n"
        f"{quote.expiry_date.strftime('%B %d, %Y')}\n"
        "\n"
        if quote.expiry_date is not None
        else ""
    )

    subject = t(language, "quote_email_subject").format(quote_number=quote_number)
    body = (
        f"{t(language, 'email_greeting').format(name=customer.name)}\n"
        "\n"
        f"{t(language, 'quote_email_intro')}\n"
        "\n"
        f"{t(language, 'quote_email_number_label')}\n"
        f"{quote_number}\n"
        "\n"
        f"{expiry_line}"
        f"{t(language, 'email_total_label')}\n"
        f"{format_amount(quote.total, currency_code)}\n"
        "\n"
        f"{t(language, 'quote_status_label')}\n"
        f"{status_label}\n"
        "\n"
        f"{t(language, 'quote_email_accept_label')}\n"
        f"{accept_link}\n"
        "\n"
        f"{t(language, 'quote_email_reject_label')}\n"
        f"{reject_link}\n"
        "\n"
        f"{t(language, 'email_thanks')}"
    )
    return subject, body


def build_quote_reminder_email(
    quote: Quote, customer: Customer, days_until_expiry: int
) -> tuple[str, str]:
    """Returns (subject, plain-text body) for an automatic "quote expiring
    soon" reminder -- mirrors app.email.reminder_templates's
    build_before_due_reminder_email shape, adapted to expiry rather than
    due date."""
    language = get_language(quote)
    currency_code = get_currency_code(quote)
    quote_number = format_quote_number(quote.quote_number)

    subject = t(language, "quote_reminder_before_expiry_subject").format(quote_number=quote_number)
    body = (
        f"{t(language, 'quote_reminder_before_expiry_greeting').format(name=customer.name)}\n"
        "\n"
        f"{t(language, 'quote_reminder_before_expiry_intro').format(days=days_until_expiry)}\n"
        "\n"
        f"{t(language, 'quote_email_number_label')}\n"
        f"{quote_number}\n"
        "\n"
        f"{t(language, 'quote_expiry_date_label')}:\n"
        f"{quote.expiry_date.strftime('%B %d, %Y')}\n"
        "\n"
        f"{t(language, 'email_total_label')}\n"
        f"{format_amount(quote.total, currency_code)}\n"
        "\n"
        f"{t(language, 'reminder_closing')}\n"
        f"{t(language, 'reminder_thanks')}"
    )
    return subject, body
