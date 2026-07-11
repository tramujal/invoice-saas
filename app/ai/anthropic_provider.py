"""Anthropic Messages API provider — the concrete implementation behind
app.ai.base.AIProvider. Calls the API directly via `requests` (matching
app/email/resend_provider.py's approach) rather than an SDK, so the exact
request shape is fully under our control.

Swapping providers later means writing a new class satisfying the same
AIProvider interface and changing the single construction line in
app/ai/factory.py — nothing else in the app needs to change.
"""

import json
import logging
from collections.abc import Iterator

import requests

from app.ai.base import AIProvider, AIProviderError, AIProviderTimeoutError, ChatMessage

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    def __init__(
        self, api_key: str, model: str, max_output_tokens: int, timeout_seconds: float
    ):
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        # Populated from the stream's message_start/message_delta events, if
        # the provider returns them — read by the caller after the stream is
        # fully consumed, for logging only (see app/routers/assistant.py).
        self.last_usage: dict[str, int | None] | None = None

    def stream_complete(self, system: str, messages: list[ChatMessage]) -> Iterator[str]:
        payload = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

        # Never log self.api_key, `system` (system prompt + business
        # context), or message content — only that a call is being made,
        # to which model, with how many prior messages. Matches
        # ResendEmailSender's logging convention exactly.
        logger.info(
            "AnthropicProvider.stream_complete: calling Anthropic API model=%s message_count=%d",
            self.model,
            len(messages),
        )

        # The POST + status check happen here, eagerly — before this method
        # returns — specifically so app/routers/assistant.py can catch a
        # connection/auth/model failure with a clean HTTP status (502/504)
        # before any streaming response has started. Only text extraction
        # from an already-open, already-validated response is lazy (see
        # _iter_text_deltas below).
        try:
            response = requests.post(
                ANTHROPIC_API_URL,
                json=payload,
                headers=headers,
                stream=True,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            logger.warning(
                "AnthropicProvider.stream_complete: request timed out model=%s", self.model
            )
            raise AIProviderTimeoutError("Anthropic API request timed out") from exc
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            # Log only the status code — never the response body, which
            # could echo back parts of the request (including business
            # context) in an error message.
            logger.error(
                "AnthropicProvider.stream_complete: Anthropic API returned an error "
                "model=%s status_code=%s",
                self.model,
                status_code,
            )
            raise AIProviderError(f"Anthropic API returned status {status_code}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error(
                "AnthropicProvider.stream_complete: could not reach Anthropic API "
                "model=%s exception_type=%s",
                self.model,
                type(exc).__name__,
            )
            raise AIProviderError("Could not reach Anthropic API") from exc

        return self._iter_text_deltas(response)

    def _iter_text_deltas(self, response: requests.Response) -> Iterator[str]:
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                data_str = raw_line[len("data:") :].strip()
                if not data_str:
                    continue
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "content_block_delta":
                    delta = event.get("delta") or {}
                    text = delta.get("text")
                    if text:
                        yield text
                elif event_type == "message_start":
                    usage = (event.get("message") or {}).get("usage") or {}
                    self.last_usage = {"input_tokens": usage.get("input_tokens")}
                elif event_type == "message_delta":
                    usage = event.get("usage") or {}
                    self.last_usage = {
                        **(self.last_usage or {}),
                        "output_tokens": usage.get("output_tokens"),
                    }
        except requests.exceptions.Timeout as exc:
            raise AIProviderTimeoutError("Anthropic API stream timed out") from exc
        except requests.exceptions.RequestException as exc:
            raise AIProviderError("Anthropic API stream failed") from exc
        finally:
            response.close()
