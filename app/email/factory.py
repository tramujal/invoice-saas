import logging
import os

from fastapi import HTTPException, status

from app.email.base import EmailSender
from app.email.resend_provider import ResendEmailSender
from app.services.platform_settings import get_effective_settings

logger = logging.getLogger(__name__)


def get_email_sender() -> EmailSender:
    """FastAPI dependency resolving the configured email provider.

    Email is optional infrastructure — unlike JWT_SECRET_KEY, missing config
    here shouldn't stop the app from booting. Endpoints that need to send
    email get a clean 503 instead, only when actually invoked.

    Checks the dynamic emails_enabled switch (app.services.
    platform_settings) first -- the one shared enforcement point every
    email-sending call site in the app goes through, so disabling email
    here means the provider is never constructed and never called,
    regardless of caller. Existing callers that already wrap this call in
    `except (EmailSendError, HTTPException)` (the password-reset/
    verification anti-enumeration paths) transparently swallow this
    exactly as they already swallow "not configured" -- no change needed
    there. Callers that surface failures directly to an already-
    authenticated user (invitations, invoice/quote "send email") now
    surface "disabled" the same clear way.
    """
    settings = get_effective_settings()
    if not settings.emails_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "emails_disabled",
                "message": "Email sending is currently disabled by a platform administrator.",
            },
        )

    api_key = os.environ.get("RESEND_API_KEY")
    from_address = os.environ.get("EMAIL_FROM")

    # Never log api_key itself — only whether it's present. email_from is
    # not a secret (it's the visible From: address), so its actual value is
    # safe and useful to log.
    logger.info(
        "get_email_sender: resend_api_key_present=%s email_from=%s",
        bool(api_key),
        from_address,
    )

    if not api_key or not from_address:
        logger.warning(
            "get_email_sender: email provider NOT initialized "
            "(resend_api_key_present=%s email_from_present=%s)",
            bool(api_key),
            bool(from_address),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Email sending is not configured. Set RESEND_API_KEY and "
                "EMAIL_FROM to enable it."
            ),
        )

    logger.info("get_email_sender: email provider initialized successfully (Resend)")
    return ResendEmailSender(api_key=api_key, from_address=from_address)
