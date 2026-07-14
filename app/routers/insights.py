"""GET /organizations/{organization_id}/dashboard/insights -- the
proactive Business Insights section. Orchestrates the deterministic
engine (app/insights/engine.py, always fresh, never cached), the optional
AI narration layer (app/insights/narration.py, cached -- see
app/insights/cache.py), and returns a bounded, tenant-scoped, localized
response.

No require_verified_email -- matches the existing /dashboard and
/dashboard/analytics endpoints exactly (both already skip it; this is a
read-only view). Cost/abuse control for the AI-enhanced path comes from
the narration cache's TTL (bounds AI calls to roughly once per
organization per window regardless of how many members load the
dashboard) plus the manual-refresh rate limit below, not identity
verification.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.ai.factory import is_ai_configured
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.insights.cache import CacheEntry, fingerprint, get_cached, set_cached
from app.insights.engine import build_insights, cap_insights
from app.insights.limits import (
    INSIGHTS_AI_ENABLED,
    INSIGHTS_CACHE_TTL_SECONDS,
    INSIGHTS_FAILURE_CACHE_TTL_SECONDS,
    INSIGHTS_MAX_PRIMARY,
    INSIGHTS_MAX_SECONDARY,
)
from app.insights.models import Insight
from app.insights.narration import narrate_insights
from app.localization import get_language
from app.models import Organization, User
from app.permissions import Permission
from app.rate_limit import (
    RateLimitCheck,
    RateLimitRule,
    enforce_rate_limit,
    user_identity,
    user_ip_identity,
)
from app.schemas import (
    DashboardInsightsResponse,
    InsightCtaResponse,
    InsightMetricResponse,
    InsightRelatedEntityResponse,
    InsightResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/organizations/{organization_id}/dashboard", tags=["dashboard"]
)

# Only applied to the manual "refresh" bypass -- normal (non-refresh) loads
# are never rate-limited beyond what the narration cache's own TTL already
# bounds AI call frequency to (see app/insights/cache.py's fingerprint
# strategy).
INSIGHTS_REFRESH_RULES = (RateLimitRule(limit=10, window_seconds=3600),)


def _to_response(insight: Insight, tier: str) -> InsightResponse:
    return InsightResponse(
        id=insight.id,
        category=insight.category.value,
        severity=insight.severity.value,
        tier=tier,
        title=insight.title,
        message=insight.message,
        suggestion=insight.suggestion,
        metric=(
            InsightMetricResponse(
                currency_code=insight.metric.currency_code,
                value=insight.metric.value,
                percentage=insight.metric.percentage,
            )
            if insight.metric
            else None
        ),
        related_entity=(
            InsightRelatedEntityResponse(
                type=insight.related_entity.type,
                id=insight.related_entity.id,
                label=insight.related_entity.label,
            )
            if insight.related_entity
            else None
        ),
        cta=(
            InsightCtaResponse(type=insight.cta.type, question=insight.cta.question)
            if insight.cta
            else None
        ),
    )


@router.get("/insights", response_model=DashboardInsightsResponse)
def get_dashboard_insights(
    organization_id: str,
    request: Request,
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardInsightsResponse:
    require_permission(current_user, organization_id, Permission.insights_view, db)

    organization = db.get(Organization, organization_id)
    language = get_language(organization)
    now = datetime.now(timezone.utc)

    # Always fresh, always cheap -- never cached itself. This is the
    # response even if everything below this point is skipped or fails.
    candidates = build_insights(db, organization_id, language, now)
    fp = fingerprint(candidates)

    source = "deterministic"
    final_ordered = candidates
    ai_available = INSIGHTS_AI_ENABLED and is_ai_configured()

    if ai_available:
        if refresh:
            # Manual refresh is the only path that's ever rate-limited --
            # normal dashboard loads never touch this.
            enforce_rate_limit(
                [
                    RateLimitCheck(
                        scope="dashboard:insights_refresh:user",
                        identity=user_identity(current_user.id),
                        rules=INSIGHTS_REFRESH_RULES,
                    ),
                    RateLimitCheck(
                        scope="dashboard:insights_refresh:user_ip",
                        identity=user_ip_identity(request, current_user.id),
                        rules=INSIGHTS_REFRESH_RULES,
                    ),
                ]
            )

        cached = None if refresh else get_cached(organization_id, language, fp)
        if cached is not None:
            if cached.status == "ok" and cached.insights is not None:
                final_ordered = cached.insights
                source = "ai_enhanced"
            # cached.status == "failed" -> stay deterministic; don't retry
            # the provider again until the short negative TTL expires.
        else:
            narrated, applied = narrate_insights(candidates)
            if applied:
                final_ordered = narrated
                source = "ai_enhanced"
                set_cached(
                    organization_id,
                    language,
                    fp,
                    CacheEntry(status="ok", insights=narrated),
                    ttl_seconds=INSIGHTS_CACHE_TTL_SECONDS,
                )
            else:
                set_cached(
                    organization_id,
                    language,
                    fp,
                    CacheEntry(status="failed", insights=None),
                    ttl_seconds=INSIGHTS_FAILURE_CACHE_TTL_SECONDS,
                )

    primary, secondary = cap_insights(
        final_ordered, INSIGHTS_MAX_PRIMARY, INSIGHTS_MAX_SECONDARY
    )
    insights_response = [_to_response(i, "primary") for i in primary] + [
        _to_response(i, "secondary") for i in secondary
    ]

    return DashboardInsightsResponse(
        generated_at=now,
        source=source,
        ai_available=ai_available,
        insights=insights_response,
    )
