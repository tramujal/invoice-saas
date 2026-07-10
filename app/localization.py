"""Organization-level localization: language and translated strings.

Organization.language ("en"/"es") drives which strings the PDF and email
templates use. Adding a new language means adding one more dict below —
call sites don't change.
"""

from typing import TYPE_CHECKING

from app.payment_status import PaymentStatus

if TYPE_CHECKING:
    from app.models import Invoice, Organization

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "es")

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "invoice_title": "Invoice",
        "invoice_no_label": "Invoice No.",
        "created_label": "Issue Date",
        "due_date_label": "Due Date",
        "payment_status_label": "Payment Status",
        "from_label": "From",
        "bill_to_label": "Bill To",
        "line_description_label": "Description",
        "line_quantity_label": "Quantity",
        "line_unit_price_label": "Unit Price",
        "line_total_label": "Line Total",
        "subtotal_label": "Subtotal",
        "tax_amount_label": "Tax",
        "total_label": "Total",
        "no_customer": "No customer on file",
        "status_pending": "Pending",
        "status_paid": "Paid",
        "status_overdue": "Overdue",
        "email_subject": "Invoice {invoice_number}",
        "email_greeting": "Hello {name},",
        "email_intro": "Please find your invoice attached.",
        "email_invoice_number_label": "Invoice Number:",
        "email_total_label": "Total:",
        "email_payment_status_label": "Payment Status:",
        "email_thanks": "Thank you.",
        "password_reset_subject": "Reset your password",
        "password_reset_greeting": "Hello,",
        "password_reset_instructions": "We received a request to reset your password.",
        "password_reset_link_label": "Reset your password:",
        "password_reset_expiry": "This link expires in 30 minutes.",
        "password_reset_ignore": (
            "If you did not request this, you can safely ignore this email."
        ),
        "verification_subject": "Verify your email address",
        "verification_greeting": "Hello,",
        "verification_instructions": (
            "Please confirm your email address to finish setting up your account."
        ),
        "verification_link_label": "Verify your email:",
        "verification_expiry": "This link expires in 24 hours.",
        "verification_ignore": (
            "If you did not create an account, you can safely ignore this email."
        ),
    },
    "es": {
        "invoice_title": "Factura",
        "invoice_no_label": "Nº de factura",
        "created_label": "Fecha de emisión",
        "due_date_label": "Fecha de vencimiento",
        "payment_status_label": "Estado",
        "from_label": "Emisor",
        "bill_to_label": "Cliente",
        "line_description_label": "Descripción",
        "line_quantity_label": "Cantidad",
        "line_unit_price_label": "Precio unitario",
        "line_total_label": "Total de línea",
        "subtotal_label": "Subtotal",
        "tax_amount_label": "Impuesto",
        "total_label": "Total",
        "no_customer": "Sin cliente registrado",
        "status_pending": "Pendiente",
        "status_paid": "Pagada",
        "status_overdue": "Vencida",
        "email_subject": "Factura {invoice_number}",
        "email_greeting": "Hola {name},",
        "email_intro": "Adjuntamos su factura.",
        "email_invoice_number_label": "Número de factura:",
        "email_total_label": "Total:",
        "email_payment_status_label": "Estado de pago:",
        "email_thanks": "Gracias.",
        "password_reset_subject": "Restablece tu contraseña",
        "password_reset_greeting": "Hola,",
        "password_reset_instructions": "Recibimos una solicitud para restablecer tu contraseña.",
        "password_reset_link_label": "Restablece tu contraseña:",
        "password_reset_expiry": "Este enlace expira en 30 minutos.",
        "password_reset_ignore": (
            "Si no solicitaste esto, puedes ignorar este correo de forma segura."
        ),
        "verification_subject": "Verifica tu dirección de correo",
        "verification_greeting": "Hola,",
        "verification_instructions": (
            "Por favor confirma tu dirección de correo para terminar de configurar tu cuenta."
        ),
        "verification_link_label": "Verifica tu correo:",
        "verification_expiry": "Este enlace expira en 24 horas.",
        "verification_ignore": (
            "Si no creaste una cuenta, puedes ignorar este correo de forma segura."
        ),
    },
}


def get_language(organization: "Organization | Invoice | None" = None) -> str:
    """Returns the language code to use. Accepts either an Organization
    (its configured default) or an Invoice (its permanently-pinned
    language) — both just need a .language attribute, so this one function
    serves both without duplication. Falls back to the safe default if
    nothing is given, or the value is somehow unrecognized."""
    language = getattr(organization, "language", None) if organization is not None else None
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def t(language: str, key: str) -> str:
    """Looks up a translated string, falling back to English if the key or
    language is somehow missing (shouldn't happen for supported languages)."""
    table = _TRANSLATIONS.get(language, _TRANSLATIONS[DEFAULT_LANGUAGE])
    return table.get(key, _TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key))


def payment_status_label(language: str, status: PaymentStatus) -> str:
    return t(language, f"status_{status.value}")
