"""All dashboard-insights numeric/feature limits, centralized and
env-configurable, with conservative defaults — read once at import time,
matching the existing pattern in app/ai/limits.py.
"""

import os

# Global kill-switch, independent of whether a provider is actually
# configured — lets an operator disable the AI-enhancement path entirely
# (e.g. for cost control) without touching ANTHROPIC_API_KEY/GEMINI_API_KEY,
# which the AI assistant still needs. The feature is fully useful with
# this false or with no provider configured at all — see app/insights/engine.py.
INSIGHTS_AI_ENABLED = os.environ.get("INSIGHTS_AI_ENABLED", "true").strip().lower() != "false"

# Deliberately shorter than AI_REQUEST_TIMEOUT_SECONDS (30s default): this
# call sits on the critical path of a dashboard page load, not a
# user-initiated chat the user is already waiting on.
INSIGHTS_AI_TIMEOUT_SECONDS = float(os.environ.get("INSIGHTS_AI_TIMEOUT_SECONDS", "10"))

# How long a successful AI narration stays cached, per
# (organization, language, data fingerprint) — see app/insights/cache.py.
INSIGHTS_CACHE_TTL_SECONDS = int(os.environ.get("INSIGHTS_CACHE_TTL_SECONDS", "1800"))

# How long a FAILED AI attempt is negatively cached -- deliberately much
# shorter than the success TTL, so a transient provider blip doesn't make
# an entire organization see "AI unavailable" for up to the full success
# TTL after the provider has already recovered.
INSIGHTS_FAILURE_CACHE_TTL_SECONDS = int(
    os.environ.get("INSIGHTS_FAILURE_CACHE_TTL_SECONDS", "90")
)

INSIGHTS_MAX_PRIMARY = int(os.environ.get("INSIGHTS_MAX_PRIMARY", "3"))
INSIGHTS_MAX_SECONDARY = int(os.environ.get("INSIGHTS_MAX_SECONDARY", "3"))

# How many deterministic candidates (beyond the MAX_PRIMARY+MAX_SECONDARY
# actually shown) are offered to the AI narration step to re-rank -- keeps
# its context bounded while still giving it real room to reorder, per
# "generate more structured insights than are displayed, then rank them."
INSIGHTS_MAX_CANDIDATES_FOR_AI = int(os.environ.get("INSIGHTS_MAX_CANDIDATES_FOR_AI", "12"))

# Bounds on the AI's free-text rewrite fields -- both a UX/layout bound and
# a defensive ceiling against a model dumping something adversarially long.
INSIGHTS_MAX_TITLE_LENGTH = int(os.environ.get("INSIGHTS_MAX_TITLE_LENGTH", "120"))
INSIGHTS_MAX_MESSAGE_LENGTH = int(os.environ.get("INSIGHTS_MAX_MESSAGE_LENGTH", "400"))
INSIGHTS_MAX_SUGGESTION_LENGTH = int(os.environ.get("INSIGHTS_MAX_SUGGESTION_LENGTH", "240"))
