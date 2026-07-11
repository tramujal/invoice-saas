"""Provider-agnostic AI assistant interface.

Routers depend only on AIProvider / ChatMessage / ToolDefinition /
StreamEvent (TextDelta / ToolInvocation) / AIProviderError /
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


@dataclass
class ToolDefinition:
    """Provider-agnostic description of one callable tool, built from a
    registered app.ai.tools.base.ActionTool's input_schema (see
    app/ai/tools/registry.py). `parameters` is a plain JSON Schema dict
    (Pydantic's model_json_schema()) — each provider translates this into
    its own native tool-declaration wire format; this file and every
    router stay completely unaware of either provider's specific shape."""

    name: str
    description: str
    parameters: dict


@dataclass
class TextDelta:
    """One chunk of ordinary streamed prose."""

    text: str


@dataclass
class ToolInvocation:
    """The model chose to call a tool. `arguments` is the provider's raw,
    UNVALIDATED parsed JSON for that call — providers never validate or
    interpret it themselves; only app.routers.assistant, via the tool
    registry's Pydantic input_schema, ever treats it as trusted input."""

    name: str
    arguments: dict


StreamEvent = TextDelta | ToolInvocation


class AIProviderError(Exception):
    """Raised when the underlying provider fails for any reason other than
    a timeout (auth failure, invalid model, unreachable, non-2xx status)."""


class AIProviderTimeoutError(AIProviderError):
    """Raised specifically when the provider doesn't respond in time, so
    callers can surface a distinct, generic timeout message rather than a
    general failure message."""


class AIProvider(ABC):
    @abstractmethod
    def stream_complete(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] = (),
    ) -> Iterator[StreamEvent]:
        """Streams a completion as a sequence of StreamEvents (TextDelta
        for ordinary prose, ToolInvocation when the model calls one of
        `tools` via the provider's native tool-use/function-calling
        mechanism).

        `system` carries the system prompt plus the structured business
        context — the only place server-owned instructions and business
        data enter the request. `messages` is prior conversation history
        plus the new user message, already validated/sanitized by the
        caller (see app.schemas.AssistantChatRequest / app.routers.assistant)
        — never raw, unvalidated client input. `tools` is the small,
        explicitly registered set of actions the model may invoke (see
        app.ai.tools.registry.tool_definitions()) — there is no path for
        the model to call anything outside this list.

        Implementations must perform the initial request (auth, model
        validation, connection) eagerly, before returning, so callers can
        catch AIProviderError/AIProviderTimeoutError with a clean HTTP
        status before any streaming response has started; only the actual
        event streaming should happen lazily as the returned iterator is
        consumed. A ToolInvocation's `arguments` are yielded exactly as the
        provider returned them — unvalidated; providers never inspect,
        execute, or interpret a tool call, only relay it.
        """
        raise NotImplementedError
