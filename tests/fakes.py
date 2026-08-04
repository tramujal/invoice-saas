"""Fakes for external providers -- AI and email.

Both real providers are plain function calls (get_ai_provider() /
get_email_sender()), not FastAPI Depends(), so patching them requires
monkeypatching every module that imported that name into its own
namespace -- see the autouse fixtures in tests/conftest.py for the exact
call sites.
"""

from collections.abc import Iterator

from app.ai.base import AIProvider, AIProviderError, ChatMessage, StreamEvent, ToolDefinition
from app.email.base import EmailMessage, EmailSendError, EmailSender
from app.whatsapp.provider_base import (
    WhatsAppConnectionState,
    WhatsAppConnectionStatus,
    WhatsAppProvider,
    WhatsAppProviderError,
    WhatsAppQrCode,
)


class FakeAIProvider(AIProvider):
    """Yields a pre-scripted sequence of StreamEvents (or raises a
    pre-scripted error) instead of calling a real model. Tests configure
    `events` (or `error`) directly before the code under test runs."""

    def __init__(
        self,
        events: list[StreamEvent] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.events = events or []
        self.error = error
        self.calls: list[tuple[str, list[ChatMessage], list[ToolDefinition]]] = []

    def stream_complete(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] = (),
    ) -> Iterator[StreamEvent]:
        self.calls.append((system, list(messages), list(tools)))
        if self.error is not None:
            raise self.error
        yield from self.events


def make_ai_error() -> AIProviderError:
    return AIProviderError("fake provider failure")


# Phase 15B's FakeWebhookDispatcher (which neutralized an in-process
# Session.after_commit + ThreadPoolExecutor dispatch chain) no longer
# has anything to replace: Phase 15C's durable job queue
# (app.services.background_jobs.enqueue_job) only ever does `db.add()` --
# no thread, no network call, no autouse fake required. A test that wants
# a job actually executed calls app.jobs.worker's claim/run helpers, or
# app.services.webhook_deliveries.deliver_webhook directly, explicitly.


class FakeEmailSender(EmailSender):
    """Collects every EmailMessage handed to it instead of calling Resend.
    Tests assert on `.sent` (recipient/subject/body/attachments) rather
    than on any network call. `fail_next_n` lets a test simulate a
    provider failure (EmailSendError) for a bounded number of sends
    without affecting later, unrelated sends -- e.g. proving one failed
    reminder doesn't corrupt or abort an independent one."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.fail_next_n: int = 0

    def send(self, message: EmailMessage) -> None:
        if self.fail_next_n > 0:
            self.fail_next_n -= 1
            raise EmailSendError("simulated provider failure")
        self.sent.append(message)


class FakeWhatsAppProvider(WhatsAppProvider):
    """Controllable WhatsAppProvider for tests -- Phase 23. Records every
    call so a test can assert exactly what text/document was sent to which
    phone number, and can be pre-configured to fail (via `.fail_next_send`)
    to exercise error/retry paths without a real bridge."""

    def __init__(self) -> None:
        self.state = WhatsAppConnectionState.connected
        self.connected_phone_number: str | None = "+15550000000"
        self.sent_text: list[tuple[str, str]] = []
        self.sent_documents: list[tuple[str, str, bytes, str]] = []
        self.fail_next_send = False
        self.qr_requested = 0
        self.reconnect_calls = 0
        self.disconnect_calls = 0
        self.delete_session_calls = 0

    def get_connection_status(self) -> WhatsAppConnectionStatus:
        return WhatsAppConnectionStatus(
            state=self.state, connected_phone_number=self.connected_phone_number, last_heartbeat_at=None
        )

    def request_qr_code(self) -> WhatsAppQrCode:
        self.qr_requested += 1
        return WhatsAppQrCode(qr_data_base64="ZmFrZS1xcg==", expires_at="2026-01-01T00:00:00Z")

    def send_text_message(self, phone_number: str, text: str) -> None:
        if self.fail_next_send:
            self.fail_next_send = False
            raise WhatsAppProviderError("simulated send failure")
        self.sent_text.append((phone_number, text))

    def send_document(self, phone_number: str, filename: str, content: bytes, mime_type: str) -> None:
        if self.fail_next_send:
            self.fail_next_send = False
            raise WhatsAppProviderError("simulated send failure")
        self.sent_documents.append((phone_number, filename, content, mime_type))

    def reconnect(self) -> None:
        self.reconnect_calls += 1

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def delete_session(self) -> None:
        self.delete_session_calls += 1
