"""Provider-agnostic email interface.

Routers depend only on EmailSender/EmailMessage/EmailSendError. Swapping the
underlying provider (Resend today) means writing a new class here and
updating the factory in app/email/factory.py — nothing else changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/pdf"


@dataclass
class EmailMessage:
    to: str
    subject: str
    text_body: str
    attachments: list[EmailAttachment]


class EmailSendError(Exception):
    """Raised when the underlying provider fails to send a message."""


class EmailSender(ABC):
    @abstractmethod
    def send(self, message: EmailMessage) -> None:
        raise NotImplementedError
