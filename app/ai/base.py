"""Provider-agnostic AI assistant interface.

Routers depend only on AIProvider / ChatMessage / AIProviderError /
AIProviderTimeoutError. Adding a new underlying provider (Anthropic and
Gemini today, selected at runtime by the AI_PROVIDER env var) means
writing a new class implementing stream_complete() and adding one branch
in app/ai/factory.py's get_ai_provider() — nothing else in the app
changes. Mirrors app/email/base.py's EmailSender abstraction exactly.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class ChatMessage:
    # "user" | "assistant" only — never "system". The system prompt and the
    # business context are passed separately (see stream_complete's
    # `system` parameter), never as an entry in this list, so a provider
    # implementation can never confuse untrusted conversation content with
    # server-owned instructions.
    role: str
    content: str


class AIProviderError(Exception):
    """Raised when the underlying provider fails for any reason other than
    a timeout (auth failure, invalid model, unreachable, non-2xx status)."""


class AIProviderTimeoutError(AIProviderError):
    """Raised specifically when the provider doesn't respond in time, so
    callers can surface a distinct, generic timeout message rather than a
    general failure message."""


class AIProvider(ABC):
    @abstractmethod
    def stream_complete(self, system: str, messages: list[ChatMessage]) -> Iterator[str]:
        """Streams a completion as a sequence of text deltas.

        `system` carries the system prompt plus the structured business
        context — the only place server-owned instructions and business
        data enter the request. `messages` is prior conversation history
        plus the new user message, already validated/sanitized by the
        caller (see app.schemas.AssistantChatRequest / app.routers.assistant)
        — never raw, unvalidated client input.

        Implementations must perform the initial request (auth, model
        validation, connection) eagerly, before returning, so callers can
        catch AIProviderError/AIProviderTimeoutError with a clean HTTP
        status before any streaming response has started; only the actual
        text streaming should happen lazily as the returned iterator is
        consumed.
        """
        raise NotImplementedError
