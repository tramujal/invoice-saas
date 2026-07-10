"""Resend (https://resend.com) email provider.

Calls Resend's REST API directly (POST /emails) via `requests` rather than
depending on the official Resend SDK, so the exact request shape is fully
under our control and doesn't depend on a moving third-party wrapper — this
is the only file in the app aware that Resend exists.

Previously used urllib.request. Switched to `requests` because urllib's
default outbound request was being blocked at the edge (Cloudflare 403,
"error code: 1010") before ever reaching Resend's API — visible as "No
activity" in the Resend dashboard. `requests` is a more standard,
production-grade HTTP client with its own connection handling.
"""

import base64
import json
import logging

import requests

from app.email.base import EmailMessage, EmailSendError, EmailSender

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailSender(EmailSender):
    def __init__(self, api_key: str, from_address: str):
        self._api_key = api_key
        self._from_address = from_address

    def send(self, message: EmailMessage) -> None:
        payload = {
            "from": self._from_address,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text_body,
            "attachments": [
                {
                    "filename": attachment.filename,
                    "content": base64.b64encode(attachment.content).decode("ascii"),
                }
                for attachment in message.attachments
            ],
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # Never log self._api_key or the Authorization header — only that a
        # call is about to be made, and to whom.
        logger.info(
            "ResendEmailSender.send: calling Resend API url=%s recipient=%s "
            "attachment_count=%d payload_bytes=%d",
            RESEND_API_URL,
            message.to,
            len(message.attachments),
            len(body_bytes),
        )

        try:
            response = requests.post(
                RESEND_API_URL, data=body_bytes, headers=headers, timeout=15
            )
            response.raise_for_status()
            logger.info(
                "ResendEmailSender.send: Resend API call succeeded "
                "recipient=%s status_code=%s",
                message.to,
                response.status_code,
            )
        except requests.exceptions.HTTPError as exc:
            # Resend reached, but responded with an error status — log the
            # exact status/body Resend sent back before wrapping it.
            response_body = (
                exc.response.content.decode("utf-8", errors="replace")
                if exc.response is not None
                else ""
            )
            status_code = exc.response.status_code if exc.response is not None else None
            logger.exception(
                "ResendEmailSender.send: Resend API returned an HTTP error "
                "recipient=%s exception_type=%s exception_message=%s "
                "status_code=%s response_body=%s",
                message.to,
                type(exc).__name__,
                str(exc),
                status_code,
                response_body,
            )
            raise EmailSendError(
                f"Resend API returned {status_code}: {response_body}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            # The request never got an HTTP response at all (DNS failure,
            # connection refused, TLS error, timeout) — this is the branch
            # that would explain Resend's dashboard showing "No activity",
            # since the request never reached Resend's servers.
            logger.exception(
                "ResendEmailSender.send: could not reach Resend API "
                "recipient=%s exception_type=%s exception_message=%s",
                message.to,
                type(exc).__name__,
                str(exc),
            )
            raise EmailSendError(f"Could not reach Resend API: {exc}") from exc
