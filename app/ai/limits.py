"""All AI-assistant numeric limits, centralized and env-configurable, with
conservative defaults — read once at import time, matching the existing
pattern for e.g. ACCESS_TOKEN_EXPIRE_MINUTES in app/security.py.

Imported by app.schemas (request validation), app.assistant_context
(context size bound), and app.ai.factory (provider call limits), so there
is exactly one place that defines "how big is too big" for this feature.
"""

import os

# Passed to the provider as the max tokens it may generate in one reply —
# keeps responses (and cost) bounded regardless of what's asked.
AI_MAX_OUTPUT_TOKENS = int(os.environ.get("AI_MAX_OUTPUT_TOKENS", "1024"))

# How long we wait for the provider before treating the call as failed.
AI_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "30"))

# The current user message. 2000 characters is generous for a question,
# stingy for an attempt to smuggle in a large payload.
AI_MAX_USER_MESSAGE_LENGTH = int(os.environ.get("AI_MAX_USER_MESSAGE_LENGTH", "2000"))

# Conversation history sent by the (untrusted) client on each call.
AI_MAX_HISTORY_MESSAGES = int(os.environ.get("AI_MAX_HISTORY_MESSAGES", "12"))
AI_MAX_HISTORY_MESSAGE_LENGTH = int(os.environ.get("AI_MAX_HISTORY_MESSAGE_LENGTH", "2000"))
AI_MAX_HISTORY_TOTAL_CHARS = int(os.environ.get("AI_MAX_HISTORY_TOTAL_CHARS", "8000"))

# Defensive ceiling on the server-built business-context text itself. The
# bounded queries in app.assistant_context (10 overdue / 10 recent / 5 top
# customers / 10 stale customers / 6 months of analytics) should never get
# close to this in practice — it's a belt-and-suspenders cap, not the
# primary control.
AI_MAX_CONTEXT_CHARS = int(os.environ.get("AI_MAX_CONTEXT_CHARS", "6000"))

# Maximum line items the AI's create_invoice_draft tool will accept in one
# proposal — same purpose as every other AI_MAX_* cap: a defensive ceiling
# independent of whatever the model or a malicious client tries to send.
# Per-line amount limits are already enforced by InvoiceLineItemCreate's
# own field constraints (app/schemas.py), reused as-is by the tool.
AI_MAX_LINE_ITEMS = int(os.environ.get("AI_MAX_LINE_ITEMS", "20"))

# How long an AI-proposed action stays confirmable before it silently
# expires. Short on purpose — a proposal is only ever meant to be
# confirmed within the same live chat session, not saved for later.
ASSISTANT_ACTION_TTL_SECONDS = int(os.environ.get("ASSISTANT_ACTION_TTL_SECONDS", "600"))
