"""The deterministic dashboard insights engine -- computes every insight
from real database data in Python/SQL. This is the primary path, not a
mere fallback: it's what renders whenever AI narration is unavailable,
disabled, or invalid (see app/insights/narration.py), and it is always
computed fresh on every request -- never cached itself (only the optional
AI rewrite of this output is cached; see app/insights/cache.py).

Severity formulas (documented here since this is the part most likely to
need tuning against real data later):
- revenue trend: growth_percent magnitude, weighted more heavily negative
  (>= +10% positive; -10%..+10% info/stable; -30%..-10% warning;
  <= -30% critical). A currency with zero revenue in both months produces
  no insight at all -- nothing happened, nothing to say.
- overdue: overdue amount as a percentage of that currency's total
  revenue (>= 30% critical; >= 10% warning; else info; unknown ratio, i.e.
  zero recorded revenue at all, treated as warning since overdue money
  exists regardless).
- pending: same ratio, but only surfaced once it crosses
  PENDING_EXPOSURE_WARNING_THRESHOLD -- pending balances are normal in
  small amounts and not worth mentioning otherwise (see the threshold's
  own comment below).
- concentration: the top customer's share of that currency's revenue,
  only surfaced once it crosses CONCENTRATION_WARNING_THRESHOLD.
- inactivity: warning if any previously-active customer has gone quiet
  90+ days, else info; never-invoiced customers are a data-quality signal,
  not an inactivity one (a customer who was never converted isn't
  "inactive").

Every insight carries at most one currency_code via its metric -- never a
value derived by combining currency_code values across currencies. Each
category produces at most one insight per currency (or one insight
organization-wide for signals that are legitimately currency-agnostic,
e.g. invoice counts), never several near-duplicate insights for the same
underlying situation.

build_insights() returns the FULL, diversity-ordered candidate list,
unbounded -- capping to what's actually shown (INSIGHTS_MAX_PRIMARY +
INSIGHTS_MAX_SECONDARY) happens in cap_insights(), called either directly
(AI unavailable) or after the AI narration layer has re-ordered by its own
`ranked_ids` (see app/insights/narration.py) -- the same cap function
either way.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_activity import get_last_invoice_at_by_customer
from app.insights.models import (
    Insight,
    InsightCategory,
    InsightCta,
    InsightMetric,
    InsightRelatedEntity,
    InsightSeverity,
    SEVERITY_RANK,
)
from app.insights.queries import (
    get_customers_missing_phone_count,
    get_invoices_without_customer_count,
    get_overdue_invoice_details,
)
from app.invoice_numbering import format_invoice_number
from app.localization import t
from app.models import Customer
from app.routers.dashboard import (
    get_dashboard_analytics_data,
    get_dashboard_summary,
    get_pending_total_by_currency,
)

# Pending balance flagged only once it exceeds this share of that
# currency's total revenue -- chosen to be meaningful enough to flag
# cash-flow risk without firing on every organization that simply has
# some invoices still awaiting payment, which is normal and not alarming
# on its own.
PENDING_EXPOSURE_WARNING_THRESHOLD = 0.4
PENDING_EXPOSURE_CRITICAL_THRESHOLD = 0.7

# A single customer representing this much of one currency's revenue is
# flagged as concentration risk -- 50% is the conventional "more than
# everyone else combined" threshold.
CONCENTRATION_WARNING_THRESHOLD = 0.5
CONCENTRATION_CRITICAL_THRESHOLD = 0.75

OVERDUE_WARNING_THRESHOLD = 0.10
OVERDUE_CRITICAL_THRESHOLD = 0.30

INACTIVITY_MIN_DAYS = 30
INACTIVITY_WARNING_DAYS = 90

MOST_PAID_THRESHOLD = 0.8
HIGH_OVERDUE_SHARE_THRESHOLD = 0.3
VOLUME_CHANGE_NOTABLE_THRESHOLD = 10.0  # percent


def _severity_priority(severity: InsightSeverity, magnitude: float) -> float:
    """`magnitude` must already be normalized to roughly [0, 1] (a ratio,
    or a percentage / 100) so it can never let one category's raw units
    (days, currency amounts) dominate the tiebreaker in an uncomparable
    way -- severity is always the primary sort key, magnitude only breaks
    ties within the same severity."""
    clamped = max(0.0, min(magnitude, 1.0))
    return SEVERITY_RANK[severity] * 1000 + clamped * 999


def _pct(part: Decimal, whole: Decimal) -> float | None:
    if whole is None or whole <= 0:
        return None
    return float((part / whole) * 100)


def build_insights(
    db: Session, organization_id: str, language: str, now: datetime
) -> list[Insight]:
    """Computes every deterministic insight candidate for this
    organization and returns them in diversity-aware priority order
    (highest first), uncapped. Callers cap via cap_insights()."""
    summary = get_dashboard_summary(db, organization_id)

    if summary.total_invoices == 0:
        return [_new_business_no_invoices(language)]

    analytics = get_dashboard_analytics_data(db, organization_id)
    # Computed once here and passed down -- both inactivity and
    # data-quality need "last invoice date per customer" and the full
    # customer list; neither re-queries it independently.
    last_invoice_at = get_last_invoice_at_by_customer(db, organization_id)
    customers = db.scalars(
        select(Customer).where(Customer.organization_id == organization_id)
    ).all()

    candidates: list[Insight] = []
    candidates.extend(_revenue_trend_insights(summary, language))
    candidates.extend(_overdue_insights(db, organization_id, summary, language))
    candidates.extend(_pending_insights(db, organization_id, summary, language))
    candidates.extend(_concentration_insights(summary, analytics, language))

    inactivity = _inactivity_insight(last_invoice_at, customers, now, language)
    if inactivity is not None:
        candidates.append(inactivity)

    volume = _volume_insight(analytics, language)
    if volume is not None:
        candidates.append(volume)

    status = _status_distribution_insight(summary, language)
    if status is not None:
        candidates.append(status)

    if summary.total_invoices == 1:
        candidates.append(_new_business_first_invoice(language))

    multi_currency = _multi_currency_insight(summary, language)
    if multi_currency is not None:
        candidates.append(multi_currency)

    data_quality = _data_quality_insight(
        db, organization_id, last_invoice_at, len(customers), language
    )
    if data_quality is not None:
        candidates.append(data_quality)

    return _diversity_order(candidates)


def _diversity_order(candidates: list[Insight]) -> list[Insight]:
    """Sorts by priority_score descending, then re-interleaves so the
    single highest-priority insight from every distinct category is
    preferred over a second insight from a category already represented
    -- otherwise one category firing once per currency (e.g. revenue
    trend in a 3-currency org) could consume the entire primary slate on
    its own, starving every other category."""
    ranked = sorted(candidates, key=lambda i: i.priority_score, reverse=True)

    seen_categories: set[InsightCategory] = set()
    first_pass: list[Insight] = []
    rest: list[Insight] = []
    for insight in ranked:
        if insight.category not in seen_categories:
            first_pass.append(insight)
            seen_categories.add(insight.category)
        else:
            rest.append(insight)

    return first_pass + rest


def cap_insights(
    ordered: list[Insight], max_primary: int, max_secondary: int
) -> tuple[list[Insight], list[Insight]]:
    """Splits an already-ordered insight list (deterministic diversity
    order, or the AI's ranked_ids order -- see app/insights/narration.py)
    into (primary, secondary), each capped at the given size."""
    primary = ordered[:max_primary]
    secondary = ordered[max_primary : max_primary + max_secondary]
    return primary, secondary


# --- category builders -------------------------------------------------


def _new_business_no_invoices(language: str) -> Insight:
    return Insight(
        id="new_business:no_invoices",
        category=InsightCategory.new_business,
        severity=InsightSeverity.info,
        title=t(language, "insight_no_invoices_title"),
        message=t(language, "insight_no_invoices_message"),
        suggestion=t(language, "insight_no_invoices_suggestion"),
        metric=None,
        related_entity=None,
        cta=InsightCta(type="create_invoice"),
        priority_score=_severity_priority(InsightSeverity.info, 0.5),
    )


def _new_business_first_invoice(language: str) -> Insight:
    return Insight(
        id="new_business:first_invoice",
        category=InsightCategory.new_business,
        severity=InsightSeverity.positive,
        title=t(language, "insight_first_invoice_title"),
        message=t(language, "insight_first_invoice_message"),
        suggestion=None,
        metric=None,
        related_entity=None,
        cta=None,
        priority_score=_severity_priority(InsightSeverity.positive, 0.3),
    )


def _revenue_trend_insights(summary, language: str) -> list[Insight]:
    insights: list[Insight] = []
    for rev in summary.revenue_by_currency:
        code = rev.currency_code
        if rev.revenue_this_month <= 0 and rev.revenue_last_month <= 0:
            continue  # nothing happened in this currency, nothing to say

        if rev.revenue_growth_percent is None:
            # last month was zero for this currency -- "first month with
            # revenue," never a divide-by-zero growth percentage (matches
            # get_dashboard_summary's own growth formula exactly).
            insights.append(
                Insight(
                    id=f"revenue_first_month:{code}",
                    category=InsightCategory.revenue,
                    severity=InsightSeverity.positive,
                    title=t(language, "insight_revenue_first_month_title").format(
                        currency=code
                    ),
                    message=t(language, "insight_revenue_first_month_message").format(
                        currency=code, amount=str(rev.revenue_this_month)
                    ),
                    suggestion=None,
                    metric=InsightMetric(
                        currency_code=code, value=rev.revenue_this_month, percentage=None
                    ),
                    related_entity=None,
                    cta=None,
                    priority_score=_severity_priority(InsightSeverity.positive, 0.3),
                )
            )
            continue

        growth = float(rev.revenue_growth_percent)
        if growth >= 10:
            severity = InsightSeverity.positive
            title_key, msg_key = (
                "insight_revenue_increase_title",
                "insight_revenue_increase_message",
            )
        elif growth <= -30:
            severity = InsightSeverity.critical
            title_key, msg_key = (
                "insight_revenue_decline_title",
                "insight_revenue_decline_message",
            )
        elif growth <= -10:
            severity = InsightSeverity.warning
            title_key, msg_key = (
                "insight_revenue_decline_title",
                "insight_revenue_decline_message",
            )
        else:
            severity = InsightSeverity.info
            title_key, msg_key = (
                "insight_revenue_stable_title",
                "insight_revenue_stable_message",
            )

        needs_attention = severity in (InsightSeverity.warning, InsightSeverity.critical)
        insights.append(
            Insight(
                id=f"revenue_trend:{code}",
                category=InsightCategory.revenue,
                severity=severity,
                title=t(language, title_key).format(
                    currency=code, percentage=f"{abs(growth):.1f}"
                ),
                message=t(language, msg_key).format(
                    currency=code,
                    this_month=str(rev.revenue_this_month),
                    last_month=str(rev.revenue_last_month),
                    percentage=f"{abs(growth):.1f}",
                ),
                suggestion=t(language, "insight_revenue_decline_suggestion")
                if needs_attention
                else None,
                metric=InsightMetric(
                    currency_code=code, value=rev.revenue_this_month, percentage=growth
                ),
                related_entity=None,
                cta=InsightCta(
                    type="ask_assistant",
                    question=t(language, "insight_revenue_ask_question").format(
                        currency=code
                    ),
                )
                if needs_attention
                else None,
                priority_score=_severity_priority(severity, min(abs(growth) / 100, 1.0)),
            )
        )
    return insights


def _overdue_insights(
    db: Session, organization_id: str, summary, language: str
) -> list[Insight]:
    details = get_overdue_invoice_details(db, organization_id)
    if not details:
        return []

    revenue_by_currency = {
        r.currency_code: r.total_revenue for r in summary.revenue_by_currency
    }
    by_currency: dict[str, list] = {}
    for detail in details:
        by_currency.setdefault(detail.currency_code, []).append(detail)

    insights: list[Insight] = []
    now = datetime.now(timezone.utc)
    for code, rows in by_currency.items():
        count = len(rows)
        amount = sum((r.total for r in rows), Decimal("0"))
        oldest = rows[0]  # already ordered oldest-first by the query
        largest = max(rows, key=lambda r: r.total)
        ratio = _pct(amount, revenue_by_currency.get(code, Decimal("0")))

        if ratio is None:
            severity = InsightSeverity.warning
        elif ratio >= OVERDUE_CRITICAL_THRESHOLD * 100:
            severity = InsightSeverity.critical
        elif ratio >= OVERDUE_WARNING_THRESHOLD * 100:
            severity = InsightSeverity.warning
        else:
            severity = InsightSeverity.info

        oldest_days = (now - oldest.created_at).days
        insights.append(
            Insight(
                id=f"overdue:{code}",
                category=InsightCategory.overdue,
                severity=severity,
                title=t(language, "insight_overdue_title").format(count=count, currency=code),
                message=t(language, "insight_overdue_message").format(
                    count=count,
                    currency=code,
                    amount=str(amount),
                    oldest_invoice=format_invoice_number(oldest.invoice_number),
                    oldest_days=oldest_days,
                    largest_invoice=format_invoice_number(largest.invoice_number),
                    largest_amount=str(largest.total),
                ),
                suggestion=t(language, "insight_overdue_suggestion"),
                metric=InsightMetric(currency_code=code, value=amount, percentage=ratio),
                related_entity=InsightRelatedEntity(
                    type="invoice",
                    id=largest.invoice_id,
                    label=format_invoice_number(largest.invoice_number),
                ),
                cta=InsightCta(type="view_overdue_invoices"),
                priority_score=_severity_priority(severity, (ratio or 30.0) / 100),
            )
        )
    return insights


def _pending_insights(
    db: Session, organization_id: str, summary, language: str
) -> list[Insight]:
    pending_by_currency = get_pending_total_by_currency(db, organization_id)
    if not pending_by_currency:
        return []

    revenue_by_currency = {
        r.currency_code: r.total_revenue for r in summary.revenue_by_currency
    }
    insights: list[Insight] = []
    for code, amount in pending_by_currency.items():
        if amount <= 0:
            continue
        ratio = _pct(amount, revenue_by_currency.get(code, Decimal("0")))
        if ratio is None or ratio < PENDING_EXPOSURE_WARNING_THRESHOLD * 100:
            continue  # not unusual enough to mention -- see module threshold rationale

        severity = (
            InsightSeverity.critical
            if ratio >= PENDING_EXPOSURE_CRITICAL_THRESHOLD * 100
            else InsightSeverity.warning
        )
        insights.append(
            Insight(
                id=f"pending:{code}",
                category=InsightCategory.pending,
                severity=severity,
                title=t(language, "insight_pending_title").format(currency=code),
                message=t(language, "insight_pending_message").format(
                    currency=code, amount=str(amount), percentage=f"{ratio:.0f}"
                ),
                suggestion=t(language, "insight_pending_suggestion"),
                metric=InsightMetric(currency_code=code, value=amount, percentage=ratio),
                related_entity=None,
                cta=InsightCta(type="review_pending_invoices"),
                priority_score=_severity_priority(severity, ratio / 100),
            )
        )
    return insights


def _concentration_insights(summary, analytics, language: str) -> list[Insight]:
    revenue_by_currency = {
        r.currency_code: r.total_revenue for r in summary.revenue_by_currency
    }
    top_by_currency: dict[str, object] = {}
    for row in analytics.top_customers:
        # top_customers is already ranked descending and capped per
        # currency in get_dashboard_analytics_data -- the first row seen
        # per currency, in iteration order, is that currency's top customer.
        if row.currency_code not in top_by_currency:
            top_by_currency[row.currency_code] = row

    insights: list[Insight] = []
    for code, top in top_by_currency.items():
        ratio = _pct(top.revenue, revenue_by_currency.get(code, Decimal("0")))
        if ratio is None or ratio < CONCENTRATION_WARNING_THRESHOLD * 100:
            continue

        severity = (
            InsightSeverity.critical
            if ratio >= CONCENTRATION_CRITICAL_THRESHOLD * 100
            else InsightSeverity.warning
        )
        insights.append(
            Insight(
                id=f"concentration:{code}",
                category=InsightCategory.concentration,
                severity=severity,
                title=t(language, "insight_concentration_title").format(currency=code),
                message=t(language, "insight_concentration_message").format(
                    customer=top.customer_name, currency=code, percentage=f"{ratio:.0f}"
                ),
                suggestion=t(language, "insight_concentration_suggestion"),
                metric=InsightMetric(currency_code=code, value=top.revenue, percentage=ratio),
                related_entity=InsightRelatedEntity(
                    type="customer", id=top.customer_id, label=top.customer_name
                ),
                cta=InsightCta(
                    type="ask_assistant",
                    question=t(language, "insight_concentration_ask_question"),
                ),
                priority_score=_severity_priority(severity, ratio / 100),
            )
        )
    return insights


def _inactivity_insight(
    last_invoice_at: dict[str, datetime],
    customers: list[Customer],
    now: datetime,
    language: str,
) -> Insight | None:
    if not last_invoice_at:
        return None  # no customer has ever been invoiced -- nothing "went quiet"

    names_by_id = {c.id: c.name for c in customers}
    quiet: list[tuple[str, int]] = []
    for customer_id, last_at in last_invoice_at.items():
        days = (now - last_at).days
        if days >= INACTIVITY_MIN_DAYS:
            quiet.append((customer_id, days))

    if not quiet:
        return None

    quiet.sort(key=lambda pair: pair[1], reverse=True)
    most_quiet_id, most_quiet_days = quiet[0]
    most_quiet_name = names_by_id.get(most_quiet_id, "")

    severity = (
        InsightSeverity.warning if most_quiet_days >= INACTIVITY_WARNING_DAYS else InsightSeverity.info
    )
    return Insight(
        id="inactivity",
        category=InsightCategory.inactivity,
        severity=severity,
        title=t(language, "insight_inactivity_title").format(count=len(quiet)),
        message=t(language, "insight_inactivity_message").format(
            count=len(quiet), customer=most_quiet_name, days=most_quiet_days
        ),
        suggestion=t(language, "insight_inactivity_suggestion"),
        metric=InsightMetric(currency_code=None, value=None, percentage=None),
        related_entity=InsightRelatedEntity(
            type="customer", id=most_quiet_id, label=most_quiet_name
        ),
        cta=InsightCta(
            type="ask_assistant",
            question=t(language, "insight_inactivity_ask_question").format(
                customer=most_quiet_name
            ),
        ),
        priority_score=_severity_priority(severity, min(most_quiet_days / 180, 1.0)),
    )


def _volume_insight(analytics, language: str) -> Insight | None:
    points = analytics.monthly_summary
    if len(points) < 2:
        return None
    this_month = points[-1].invoice_count
    last_month = points[-2].invoice_count

    if this_month == 0 and last_month == 0:
        return None  # nothing to compare -- the no-invoices case is handled separately

    if last_month == 0:
        return Insight(
            id="volume_first_month",
            category=InsightCategory.volume,
            severity=InsightSeverity.positive,
            title=t(language, "insight_volume_first_month_title"),
            message=t(language, "insight_volume_first_month_message").format(count=this_month),
            suggestion=None,
            metric=InsightMetric(currency_code=None, value=Decimal(this_month), percentage=None),
            related_entity=None,
            cta=None,
            priority_score=_severity_priority(InsightSeverity.positive, 0.2),
        )

    change_pct = ((this_month - last_month) / last_month) * 100
    if abs(change_pct) < VOLUME_CHANGE_NOTABLE_THRESHOLD:
        return None  # not a meaningful enough change to call out

    severity = InsightSeverity.positive if change_pct > 0 else InsightSeverity.warning
    title_key = (
        "insight_volume_increase_title" if change_pct > 0 else "insight_volume_decrease_title"
    )
    return Insight(
        id="volume_change",
        category=InsightCategory.volume,
        severity=severity,
        title=t(language, title_key).format(percentage=f"{abs(change_pct):.0f}"),
        message=t(language, "insight_volume_message").format(
            this_month=this_month, last_month=last_month, percentage=f"{abs(change_pct):.0f}"
        ),
        suggestion=None,
        metric=InsightMetric(currency_code=None, value=Decimal(this_month), percentage=change_pct),
        related_entity=None,
        cta=None,
        priority_score=_severity_priority(severity, min(abs(change_pct) / 100, 1.0)),
    )


def _status_distribution_insight(summary, language: str) -> Insight | None:
    total = summary.total_invoices
    if total == 0:
        return None
    pending, paid, overdue = (
        summary.pending_invoices,
        summary.paid_invoices,
        summary.overdue_invoices,
    )

    overdue_share = overdue / total
    if overdue_share >= HIGH_OVERDUE_SHARE_THRESHOLD:
        return Insight(
            id="status_distribution:high_overdue",
            category=InsightCategory.status_distribution,
            severity=InsightSeverity.warning,
            title=t(language, "insight_status_high_overdue_title"),
            message=t(language, "insight_status_high_overdue_message").format(
                overdue=overdue, total=total, percentage=f"{overdue_share * 100:.0f}"
            ),
            suggestion=t(language, "insight_overdue_suggestion"),
            metric=InsightMetric(currency_code=None, value=None, percentage=overdue_share * 100),
            related_entity=None,
            cta=InsightCta(type="view_overdue_invoices"),
            priority_score=_severity_priority(InsightSeverity.warning, overdue_share),
        )

    if pending == total and paid == 0 and overdue == 0:
        return Insight(
            id="status_distribution:all_pending",
            category=InsightCategory.status_distribution,
            severity=InsightSeverity.info,
            title=t(language, "insight_status_all_pending_title"),
            message=t(language, "insight_status_all_pending_message").format(count=total),
            suggestion=None,
            metric=None,
            related_entity=None,
            cta=InsightCta(type="review_pending_invoices"),
            priority_score=_severity_priority(InsightSeverity.info, 0.3),
        )

    if paid == 0 and overdue > 0:
        return Insight(
            id="status_distribution:no_paid_yet",
            category=InsightCategory.status_distribution,
            severity=InsightSeverity.warning,
            title=t(language, "insight_status_no_paid_title"),
            message=t(language, "insight_status_no_paid_message").format(overdue=overdue),
            suggestion=t(language, "insight_overdue_suggestion"),
            metric=None,
            related_entity=None,
            cta=InsightCta(type="view_overdue_invoices"),
            priority_score=_severity_priority(InsightSeverity.warning, 0.5),
        )

    if paid / total >= MOST_PAID_THRESHOLD:
        return Insight(
            id="status_distribution:mostly_paid",
            category=InsightCategory.status_distribution,
            severity=InsightSeverity.positive,
            title=t(language, "insight_status_mostly_paid_title"),
            message=t(language, "insight_status_mostly_paid_message").format(
                paid=paid, total=total, percentage=f"{(paid / total) * 100:.0f}"
            ),
            suggestion=None,
            metric=InsightMetric(
                currency_code=None, value=None, percentage=(paid / total) * 100
            ),
            related_entity=None,
            cta=None,
            priority_score=_severity_priority(InsightSeverity.positive, paid / total),
        )

    return None


def _multi_currency_insight(summary, language: str) -> Insight | None:
    codes = [r.currency_code for r in summary.revenue_by_currency if r.total_revenue > 0]
    if len(codes) <= 1:
        return None
    return Insight(
        id="multi_currency",
        category=InsightCategory.multi_currency,
        severity=InsightSeverity.info,
        title=t(language, "insight_multi_currency_title").format(count=len(codes)),
        message=t(language, "insight_multi_currency_message").format(
            count=len(codes), currencies=", ".join(sorted(codes))
        ),
        suggestion=None,
        metric=None,
        related_entity=None,
        cta=None,
        priority_score=_severity_priority(InsightSeverity.info, 0.1),
    )


def _data_quality_insight(
    db: Session,
    organization_id: str,
    last_invoice_at: dict[str, datetime],
    total_customers: int,
    language: str,
) -> Insight | None:
    invoices_without_customer = get_invoices_without_customer_count(db, organization_id)
    customers_missing_phone = get_customers_missing_phone_count(db, organization_id)
    never_invoiced = max(total_customers - len(last_invoice_at), 0)

    parts: list[tuple[str, int]] = []
    if invoices_without_customer > 0:
        parts.append(("invoices_without_customer", invoices_without_customer))
    if customers_missing_phone > 0:
        parts.append(("customers_missing_phone", customers_missing_phone))
    if never_invoiced > 0:
        parts.append(("customers_never_invoiced", never_invoiced))

    if not parts:
        return None

    # Pick the single most numerous condition as the headline -- keeps
    # this to one insight, never three near-duplicates for the same
    # "housekeeping" theme.
    key, count = max(parts, key=lambda p: p[1])
    return Insight(
        id=f"data_quality:{key}",
        category=InsightCategory.data_quality,
        severity=InsightSeverity.info,
        title=t(language, "insight_data_quality_title"),
        message=t(language, f"insight_data_quality_{key}_message").format(count=count),
        suggestion=None,
        metric=None,
        related_entity=None,
        cta=None,
        priority_score=_severity_priority(InsightSeverity.info, 0.05),
    )
