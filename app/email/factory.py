import os

from fastapi import HTTPException, status

from app.email.base import EmailSender
from app.email.resend_provider import ResendEmailSender


def get_email_sender() -> EmailSender:
    """FastAPI dependency resolving the configured email provider.

    Email is optional infrastructure — unlike JWT_SECRET_KEY, missing config
    here shouldn't stop the app from booting. Endpoints that need to send
    email get a clean 503 instead, only when actually invoked.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("EMAIL_FROM")
    if not api_key or not from_address:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Email sending is not configured. Set RESEND_API_KEY and "
                "EMAIL_FROM to enable it."
            ),
        )
    return ResendEmailSender(api_key=api_key, from_address=from_address)
