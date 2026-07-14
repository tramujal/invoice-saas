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
