"""Resend (https://resend.com) email provider.

Calls Resend's REST API directly (POST /emails) rather than depending on
their SDK, so the exact request shape is fully under our control and
doesn't depend on a moving third-party wrapper — this is the only file in
the app aware that Resend exists.
"""

import base64
import json
import urllib.error
import urllib.request

from app.email.base import EmailMessage, EmailSendError, EmailSender

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

        request = urllib.request.Request(
            RESEND_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmailSendError(
                f"Resend API returned {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise EmailSendError(f"Could not reach Resend API: {exc.reason}") from exc
