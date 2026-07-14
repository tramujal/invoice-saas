"""app.insights.narration.narrate_insights -- pure service-layer tests
against the real fake_ai_provider (no HTTP needed), covering the "AI can
never inject a number, and any unknown id invalidates the whole response"
safety guarantees the plan calls out explicitly."""

from app.ai.base import AIProviderError, ToolInvocation
from app.insights.models import Insight, InsightCategory, InsightMetric, InsightSeverity
from app.insights.narration import _NARRATION_TOOL_NAME, narrate_insights


def _insight(insight_id: str, title: str = "Original title") -> Insight:
    return Insight(
        id=insight_id,
        category=InsightCategory.overdue,
        severity=InsightSeverity.warning,
        title=title,
        message="Original message",
        suggestion="Original suggestion",
        metric=InsightMetric(currency_code="USD", value=100, percentage=None),
        related_entity=None,
        cta=None,
    )


def test_successful_narration_rewrites_text_but_never_metric(fake_ai_provider):
    candidates = [_insight("insight-1")]
    fake_ai_provider.events = [
        ToolInvocation(
            name=_NARRATION_TOOL_NAME,
            arguments={
                "ranked_ids": ["insight-1"],
                "narration": [
                    {"id": "insight-1", "title": "AI Title", "message": "AI message"}
                ],
            },
        )
    ]

    result, applied = narrate_insights(candidates)
    assert applied is True
    assert result[0].title == "AI Title"
    assert result[0].message == "AI message"
    # metric is never touched by narration output -- always copied from
    # the original deterministic Insight.
    assert result[0].metric == candidates[0].metric


def test_unknown_insight_id_in_narration_rejects_whole_response(fake_ai_provider):
    candidates = [_insight("insight-1")]
    fake_ai_provider.events = [
        ToolInvocation(
            name=_NARRATION_TOOL_NAME,
            arguments={
                "ranked_ids": ["insight-1"],
                "narration": [
                    {"id": "insight-does-not-exist", "title": "AI Title", "message": "AI message"}
                ],
            },
        )
    ]

    result, applied = narrate_insights(candidates)
    assert applied is False
    assert result == candidates


def test_unknown_insight_id_in_ranked_ids_rejects_whole_response(fake_ai_provider):
    candidates = [_insight("insight-1")]
    fake_ai_provider.events = [
        ToolInvocation(
            name=_NARRATION_TOOL_NAME,
            arguments={"ranked_ids": ["insight-ghost"], "narration": []},
        )
    ]

    result, applied = narrate_insights(candidates)
    assert applied is False
    assert result == candidates


def test_model_injecting_a_numeric_field_is_rejected_by_schema(fake_ai_provider):
    """InsightNarrationEntry has extra="forbid" and no numeric field at
    all -- a model trying to sneak in e.g. "value" fails Pydantic
    validation and the whole response is discarded."""
    candidates = [_insight("insight-1")]
    fake_ai_provider.events = [
        ToolInvocation(
            name=_NARRATION_TOOL_NAME,
            arguments={
                "ranked_ids": ["insight-1"],
                "narration": [
                    {
                        "id": "insight-1",
                        "title": "AI Title",
                        "message": "AI message",
                        "value": 999999,
                    }
                ],
            },
        )
    ]

    result, applied = narrate_insights(candidates)
    assert applied is False
    assert result == candidates


def test_provider_error_falls_back_to_deterministic(fake_ai_provider):
    candidates = [_insight("insight-1")]
    fake_ai_provider.error = AIProviderError("simulated failure")

    result, applied = narrate_insights(candidates)
    assert applied is False
    assert result == candidates


def test_no_tool_call_falls_back_to_deterministic(fake_ai_provider):
    """The model replying with plain text instead of calling the
    narration tool must fall back exactly like any other failure mode."""
    from app.ai.base import TextDelta

    candidates = [_insight("insight-1")]
    fake_ai_provider.events = [TextDelta(text="I have some thoughts but no tool call.")]

    result, applied = narrate_insights(candidates)
    assert applied is False
    assert result == candidates


def test_empty_candidates_short_circuits_without_calling_provider(fake_ai_provider):
    result, applied = narrate_insights([])
    assert applied is False
    assert result == []
    assert fake_ai_provider.calls == []


def test_ai_disabled_short_circuits_without_calling_provider(fake_ai_provider, monkeypatch):
    import app.insights.narration as narration_module

    monkeypatch.setattr(narration_module, "INSIGHTS_AI_ENABLED", False)
    candidates = [_insight("insight-1")]

    result, applied = narrate_insights(candidates)
    assert applied is False
    assert result == candidates
    assert fake_ai_provider.calls == []
