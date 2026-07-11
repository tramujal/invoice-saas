"""AI narration layer for dashboard insights -- rewrites wording and
re-ranks a fixed, closed list of deterministic insights (see
app/insights/engine.py). Reuses AIProvider.stream_complete(...) completely
unchanged: a one-shot, non-conversational call, drained synchronously
inside the request handler for GET .../dashboard/insights, never streamed
to the client and never registered in the AI Agent's own TOOL_REGISTRY
(app/ai/tools/registry.py) -- a separate, narrower concept.

The core safety guarantee: InsightNarrationEntry (app/schemas.py) has no
field for any number at all -- the model can only supply title/message/
suggestion (free text) and reorder via ranked_ids. The metric/
related_entity values actually shown to the user always come from the
ORIGINAL deterministic Insight, keyed by id, never from the AI's output.
Any id the model references that isn't in the known set invalidates the
WHOLE response -- there is no partial trust.
"""

import logging
from dataclasses import replace

from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.base import (
    AIProviderError,
    AIProviderTimeoutError,
    ChatMessage,
    ToolDefinition,
    ToolInvocation,
)
from app.ai.factory import get_ai_provider
from app.insights.limits import (
    INSIGHTS_AI_ENABLED,
    INSIGHTS_AI_TIMEOUT_SECONDS,
    INSIGHTS_MAX_CANDIDATES_FOR_AI,
)
from app.insights.models import Insight
from app.insights.narration_prompt import INSIGHTS_NARRATION_SYSTEM_PROMPT
from app.schemas import InsightNarrationResponse

logger = logging.getLogger(__name__)

_NARRATION_TOOL_NAME = "submit_insight_narration"


def _build_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name=_NARRATION_TOOL_NAME,
        description="Submit your rewritten insight narration and importance ranking.",
        parameters=InsightNarrationResponse.model_json_schema(),
    )


def _render_candidates_text(candidates: list[Insight]) -> str:
    """Bounded, plain-text rendering of the candidate insights -- never a
    raw dict/JSON dump of internal fields, and never anything beyond
    id/category/severity/title/message/suggestion (no metric numbers are
    sent as separate fields either; they're already embedded in the
    deterministic title/message text the model is asked to rewrite)."""
    lines = ["INSIGHTS:"]
    for insight in candidates:
        lines.append(
            f"- id: {insight.id} | category: {insight.category.value} | "
            f"severity: {insight.severity.value}"
        )
        lines.append(f"  title: {insight.title}")
        lines.append(f"  message: {insight.message}")
        if insight.suggestion:
            lines.append(f"  suggestion: {insight.suggestion}")
    return "\n".join(lines)


def narrate_insights(candidates: list[Insight]) -> tuple[list[Insight], bool]:
    """Attempts to rewrite/rerank `candidates` (already in deterministic
    diversity order) via the configured AI provider. Returns
    (result_list, ai_applied). On ANY failure -- disabled, unconfigured,
    timeout, provider error, no tool call, invalid schema, or an unknown
    insight id anywhere in the response -- returns (candidates, False)
    completely unchanged, so the caller always has a safe list to render.
    """
    if not INSIGHTS_AI_ENABLED or not candidates:
        return candidates, False

    bounded_candidates = candidates[:INSIGHTS_MAX_CANDIDATES_FOR_AI]
    known_ids = {c.id for c in bounded_candidates}

    try:
        ai_provider = get_ai_provider(timeout_seconds=INSIGHTS_AI_TIMEOUT_SECONDS)
    except HTTPException:
        # Not configured / unknown provider -- get_ai_provider's own 503,
        # treated identically to any other "AI not available" case.
        return candidates, False

    tool = _build_tool_definition()
    messages = [ChatMessage(role="user", content=_render_candidates_text(bounded_candidates))]

    try:
        stream = ai_provider.stream_complete(
            INSIGHTS_NARRATION_SYSTEM_PROMPT, messages, tools=[tool]
        )
    except AIProviderTimeoutError:
        logger.warning("narrate_insights: provider timed out before responding")
        return candidates, False
    except AIProviderError:
        logger.warning("narrate_insights: provider failed before responding")
        return candidates, False

    invocation: ToolInvocation | None = None
    try:
        for event in stream:
            if isinstance(event, ToolInvocation) and event.name == _NARRATION_TOOL_NAME:
                invocation = event
                break
            # Any TextDelta is silently discarded -- this call is never
            # shown to the user as chat; only a tool call is a valid reply.
    except AIProviderTimeoutError:
        logger.warning("narrate_insights: provider timed out mid-response")
        return candidates, False
    except AIProviderError:
        logger.warning("narrate_insights: provider failed mid-response")
        return candidates, False

    if invocation is None:
        logger.warning("narrate_insights: model did not call the narration tool")
        return candidates, False

    try:
        parsed = InsightNarrationResponse.model_validate(invocation.arguments)
    except ValidationError:
        logger.warning("narrate_insights: model response failed schema validation")
        return candidates, False

    narration_by_id = {}
    for entry in parsed.narration:
        if entry.id not in known_ids:
            logger.warning(
                "narrate_insights: unknown insight id in narration, rejecting whole response"
            )
            return candidates, False
        narration_by_id[entry.id] = entry

    seen: set[str] = set()
    ranked_ids: list[str] = []
    for insight_id in parsed.ranked_ids:
        if insight_id not in known_ids:
            logger.warning(
                "narrate_insights: unknown insight id in ranked_ids, rejecting whole response"
            )
            return candidates, False
        if insight_id in seen:
            continue
        seen.add(insight_id)
        ranked_ids.append(insight_id)

    if not ranked_ids:
        # A successful tool call with an empty ranking means "no useful
        # reordering" -- keep the deterministic order rather than hiding
        # every insight.
        ranked_ids = [c.id for c in bounded_candidates]

    by_id = {c.id: c for c in bounded_candidates}
    result: list[Insight] = []
    for insight_id in ranked_ids:
        original = by_id[insight_id]
        narration = narration_by_id.get(insight_id)
        if narration is None:
            # The model chose not to comment on this one -- keep the
            # deterministic wording rather than dropping the insight.
            result.append(original)
            continue
        # Only title/message/suggestion ever come from `narration` --
        # metric/related_entity/cta/severity/category/id are always
        # copied from the original deterministic Insight, never touched
        # by AI output.
        result.append(
            replace(
                original,
                title=narration.title,
                message=narration.message,
                suggestion=(
                    narration.suggestion if narration.suggestion is not None else original.suggestion
                ),
            )
        )

    return result, True
