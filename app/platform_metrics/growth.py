"""Growth metrics: daily signups, weekly active organizations, monthly
growth, and feature adoption. Every figure is derived from
OrganizationMember (the same org/user creation-time proxy
app.routers.platform_admin already established -- neither Organization
nor User has its own created_at column), Invoice/Quote/Customer/Product
(the same four tables platform_admin.py's own `_last_activity_map`
already treats as "real activity," extended here into a weekly series
instead of a single latest timestamp), and Subscription/Plan for
feature adoption.

Date bucketing is done in Python (group raw rows by day/week key), not
with a database-specific `date_trunc`/`strftime` SQL function -- the
same convention app.analytics.calculators already uses, since it works
identically on SQLite and Postgres without a dialect branch.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PLAN_CODE_FREE, Customer, Invoice, OrganizationMember, Plan, Product, Quote, Subscription
from app.subscription_status import SubscriptionStatus

_ACTIVITY_MODELS = (Invoice, Quote, Customer, Product)
_FEATURE_FLAGS = (
    "analytics_enabled",
    "forecasting_enabled",
    "ai_enabled",
    "background_jobs_enabled",
    "custom_branding_enabled",
    "api_access_enabled",
    "advanced_reports_enabled",
)
_PAYING_STATUSES = (SubscriptionStatus.active.value, SubscriptionStatus.past_due.value)


@dataclass(frozen=True)
class DailyCount:
    day: date
    count: int


@dataclass(frozen=True)
class WeeklyCount:
    week_start: date
    count: int


@dataclass(frozen=True)
class FeatureAdoption:
    feature: str
    adopted_paying_organizations: int
    adopted_percent: float


@dataclass(frozen=True)
class GrowthMetrics:
    daily_signups: list[DailyCount]
    weekly_active_organizations: list[WeeklyCount]
    monthly_growth_percent: float
    feature_adoption: list[FeatureAdoption]


def _week_start(moment: datetime) -> date:
    d = moment.date()
    return d - timedelta(days=d.weekday())


def _daily_signups(db: Session, since: datetime) -> list[DailyCount]:
    first_membership_per_org = (
        select(OrganizationMember.organization_id, func.min(OrganizationMember.created_at).label("first_at"))
        .group_by(OrganizationMember.organization_id)
        .subquery()
    )
    rows = db.execute(
        select(first_membership_per_org.c.first_at).where(first_membership_per_org.c.first_at >= since)
    ).all()

    counts: dict[date, int] = {}
    for (first_at,) in rows:
        day = first_at.date() if isinstance(first_at, datetime) else first_at
        counts[day] = counts.get(day, 0) + 1

    return sorted((DailyCount(day=day, count=count) for day, count in counts.items()), key=lambda dc: dc.day)


def _weekly_active_organizations(db: Session, since: datetime) -> list[WeeklyCount]:
    weeks: dict[date, set[str]] = {}
    for model in _ACTIVITY_MODELS:
        rows = db.execute(
            select(model.organization_id, model.created_at).where(model.created_at >= since)
        ).all()
        for org_id, created_at in rows:
            week = _week_start(created_at)
            weeks.setdefault(week, set()).add(org_id)

    return sorted(
        (WeeklyCount(week_start=week, count=len(org_ids)) for week, org_ids in weeks.items()),
        key=lambda wc: wc.week_start,
    )


def _monthly_growth_percent(db: Session, now: datetime) -> float:
    since_30d = now - timedelta(days=30)
    first_membership_per_org = (
        select(OrganizationMember.organization_id, func.min(OrganizationMember.created_at).label("first_at"))
        .group_by(OrganizationMember.organization_id)
        .subquery()
    )
    total_now = db.scalar(select(func.count()).select_from(first_membership_per_org)) or 0
    total_30d_ago = (
        db.scalar(
            select(func.count())
            .select_from(first_membership_per_org)
            .where(first_membership_per_org.c.first_at < since_30d)
        )
        or 0
    )
    if total_30d_ago == 0:
        return 100.0 if total_now > 0 else 0.0
    return round((total_now - total_30d_ago) / total_30d_ago * 100, 2)


def _feature_adoption(db: Session) -> list[FeatureAdoption]:
    rows = db.execute(
        select(
            Plan.code,
            *[getattr(Plan, flag) for flag in _FEATURE_FLAGS],
        )
        .select_from(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.status.in_(_PAYING_STATUSES))
    ).all()

    paying_total = sum(1 for row in rows if row[0] != PLAN_CODE_FREE)
    adoption: list[FeatureAdoption] = []
    for index, flag in enumerate(_FEATURE_FLAGS, start=1):
        adopted = sum(1 for row in rows if row[0] != PLAN_CODE_FREE and row[index])
        percent = (adopted / paying_total * 100) if paying_total else 0.0
        adoption.append(
            FeatureAdoption(feature=flag, adopted_paying_organizations=adopted, adopted_percent=round(percent, 2))
        )
    return adoption


def compute_growth_metrics(db: Session, *, days: int = 30) -> GrowthMetrics:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    return GrowthMetrics(
        daily_signups=_daily_signups(db, since),
        weekly_active_organizations=_weekly_active_organizations(db, since),
        monthly_growth_percent=_monthly_growth_percent(db, now),
        feature_adoption=_feature_adoption(db),
    )
