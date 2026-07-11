"""Google Gemini provider -- the concrete implementation behind
app.ai.base.AIProvider, using the official Google GenAI Python SDK
(`google-genai`, imported as `google.genai`).

Mirrors app/ai/anthropic_provider.py's structure and error-handling
contract exactly, so app/ai/factory.py can hand back either provider
behind the same AIProvider interface and app/routers/assistant.py never
needs to know or care which one is active.
"""

import logging
from collections.abc import Iterator
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.ai.base import AIProvider, AIProviderError, AIProviderTimeoutError, ChatMessage

logger = logging.getLogger(__name__)


def _to_gemini_role(role: str) -> str:
    # ChatMessage.role is "user" | "assistant" (see app/ai/base.py) -- Gemini
    # calls the assistant turn "model" instead of "assistant". This is the
    # only shape difference between the two APIs' conversation format, and
    # it's fully absorbed here so nothing above this file ever sees it.
    return "model" if role == "assistant" else "user"


class GeminiProvider(AIProvider):
    def __init__(
        self, api_key: str, model: str, max_output_tokens: int, timeout_seconds: float
    ):
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self._client = genai.Client(api_key=api_key)
        # Populated from the stream's usage_metadata, if the provider
        # returns it -- read by the caller after the stream is fully
        # consumed, for logging only (see app/routers/assistant.py).
        # Same shape as AnthropicProvider.last_usage so the router's
        # logging line never needs to know which provider produced it.
        self.last_usage: dict[str, int | None] | None = None

    def stream_complete(self, system: str, messages: list[ChatMessage]) -> Iterator[str]:
        contents = [
            {"role": _to_gemini_role(m.role), "parts": [{"text": m.content}]}
            for m in messages
        ]
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self.max_output_tokens,
            http_options=genai_types.HttpOptions(
                # HttpOptions.timeout is in milliseconds.
                timeout=int(self.timeout_seconds * 1000),
                # A single attempt, bounded strictly by `timeout` above --
                # the SDK's own default (5 attempts with exponential
                # backoff up to 60s between them) would let one call run
                # far longer than AI_REQUEST_TIMEOUT_SECONDS actually
                # promises callers.
                retry_options=genai_types.HttpRetryOptions(attempts=1),
            ),
        )

        # Never log the API key (held inside self._client, never read back
        # out here), `system` (system prompt + business context), or
        # message content -- only that a call is being made, to which
        # model, with how many prior messages. Matches AnthropicProvider's
        # logging convention exactly.
        logger.info(
            "GeminiProvider.stream_complete: calling Gemini API model=%s message_count=%d",
            self.model,
            len(messages),
        )

        # generate_content_stream(...) returns a generator that performs no
        # network I/O until first advanced. Pulling the first chunk here,
        # eagerly, before this method returns, is what actually makes the
        # request happen now rather than on the caller's first iteration --
        # matching AnthropicProvider.stream_complete's contract that
        # auth/model/connection failures surface as an exception from
        # *this* call, before any streaming response has started, not from
        # inside the returned iterator.
        try:
            raw_stream = self._client.models.generate_content_stream(
                model=self.model, contents=contents, config=config
            )
            first_chunk = next(raw_stream, None)
        except httpx.TimeoutException as exc:
            logger.warning(
                "GeminiProvider.stream_complete: request timed out model=%s", self.model
            )
            raise AIProviderTimeoutError("Gemini API request timed out") from exc
        except genai_errors.APIError as exc:
            # Log only the status code -- never exc.message/exc.details,
            # which could echo back parts of the request (including
            # business context) in an error message.
            logger.error(
                "GeminiProvider.stream_complete: Gemini API returned an error "
                "model=%s status_code=%s",
                self.model,
                exc.code,
            )
            raise AIProviderError(f"Gemini API returned status {exc.code}") from exc
        except httpx.HTTPError as exc:
            logger.error(
                "GeminiProvider.stream_complete: could not reach Gemini API "
                "model=%s exception_type=%s",
                self.model,
                type(exc).__name__,
            )
            raise AIProviderError("Could not reach Gemini API") from exc

        return self._iter_text_deltas(first_chunk, raw_stream)

    def _iter_text_deltas(
        self,
        first_chunk: genai_types.GenerateContentResponse | None,
        raw_stream: Iterator[genai_types.GenerateContentResponse],
    ) -> Iterator[str]:
        def _chunks() -> Iterator[Any]:
            if first_chunk is not None:
                yield first_chunk
            yield from raw_stream

        try:
            for chunk in _chunks():
                usage = getattr(chunk, "usage_metadata", None)
                if usage is not None:
                    self.last_usage = {
                        "input_tokens": usage.prompt_token_count,
                        "output_tokens": usage.candidates_token_count,
                    }
                text = chunk.text
                if text:
                    yield text
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutError("Gemini API stream timed out") from exc
        except genai_errors.APIError as exc:
            raise AIProviderError(f"Gemini API returned status {exc.code}") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError("Gemini API stream failed") from exc
