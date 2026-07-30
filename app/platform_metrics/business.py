"""Business metrics: organizations, active users, paying/trial split,
MRR/ARR, churn, conversion, and ARPU -- every figure here is derived
directly from Subscription/Plan/SubscriptionEvent/OrganizationMember,
the exact same tables app.billing.service.BillingService already
treats as the single source of truth for an organization's commercial
state. This module never writes to any of them.

Pricing note: MRR/ARR assume a single-currency deployment (this app has
no multi-currency billing anywhere -- Plan.currency exists per-plan but
every seeded plan uses "USD"). A subscription on a plan with NULL
pricing (Enterprise/"contact us", see Plan's own docstring) is excluded
from the MRR sum -- there is no honest number to add, and silently
treating NULL as 0 would understate nothing but also fabricate a false
precision the platform doesn't have. `paying_organizations` still counts
that organization; only the currency total omits it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing_period import BillingPeriod
from app.membership_status import MembershipStatus
from app.models import PLAN_CODE_FREE, Organization, OrganizationMember, Plan, Subscription, SubscriptionEvent
from app.subscription_event_type import SubscriptionEventType
from app.subscription_status import SubscriptionStatus


@dataclass(frozen=True)
class BusinessMetrics:
    organizations_total: int
    active_users_total: int
    paying_organizations: int
    trial_organizations: int
    mrr: Decimal
    arr: Decimal
    currency: str
    churn_rate_30d: float
    conversion_rate_30d: float
    average_revenue_per_organization: Decimal


_PAYING_STATUSES = (SubscriptionStatus.active.value, SubscriptionStatus.past_due.value)


def _normalized_monthly_price(
    *, monthly_price: Decimal | None, yearly_price: Decimal | None, billing_period: str
) -> Decimal | None:
    """Normalizes a plan's price to a monthly figure regardless of the
    subscription's own billing period -- the one place this conversion
    happens, so MRR and ARR (ARR = MRR * 12, never a second independent
    yearly-price sum) can never drift apart from each other."""
    if billing_period == BillingPeriod.yearly.value:
        if yearly_price is None:
            return None
        return yearly_price / Decimal(12)
    return monthly_price


def compute_business_metrics(db: Session) -> BusinessMetrics:
    organizations_total = db.scalar(select(func.count()).select_from(Organization)) or 0

    active_users_total = (
        db.scalar(
            select(func.count(func.distinct(OrganizationMember.user_id))).where(
                OrganizationMember.status == MembershipStatus.active.value
            )
        )
        or 0
    )

    # One pass over every (Subscription, Plan) pair -- small table by
    # construction (one row per organization), so loading it once in
    # Python to compute MRR/paying/trial together is simpler and no
    # slower than three separate aggregate queries would be.
    rows = db.execute(
        select(Subscription.status, Subscription.billing_period, Plan.code, Plan.monthly_price, Plan.yearly_price)
        .join(Plan, Plan.id == Subscription.plan_id)
    ).all()

    paying_organizations = 0
    trial_organizations = 0
    mrr = Decimal("0")
    currency = "USD"
    for status_value, billing_period, plan_code, monthly_price, yearly_price in rows:
        if status_value == SubscriptionStatus.trialing.value:
            trial_organizations += 1
            continue
        if status_value not in _PAYING_STATUSES or plan_code == PLAN_CODE_FREE:
            continue
        paying_organizations += 1
        normalized = _normalized_monthly_price(
            monthly_price=monthly_price, yearly_price=yearly_price, billing_period=billing_period
        )
        if normalized is not None:
            mrr += normalized

    arr = mrr * 12
    average_revenue_per_organization = (mrr / paying_organizations) if paying_organizations else Decimal("0")

    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)

    churned_30d = (
        db.scalar(
            select(func.count())
            .select_from(SubscriptionEvent)
            .where(
                SubscriptionEvent.event_type.in_(
                    (SubscriptionEventType.subscription_canceled.value, SubscriptionEventType.subscription_expired.value)
                ),
                SubscriptionEvent.created_at >= since_30d,
            )
        )
        or 0
    )
    # Active-at-start-of-window approximation: today's paying count plus
    # whoever churned during the window (they were paying when the
    # window started, even though they aren't now). This app keeps no
    # daily snapshot table, so this is the closest honest denominator
    # available from existing data -- documented here rather than
    # silently presented as an exact historical figure.
    active_at_window_start = paying_organizations + churned_30d
    churn_rate_30d = (churned_30d / active_at_window_start * 100) if active_at_window_start else 0.0

    trials_started_30d = (
        db.scalar(
            select(func.count())
            .select_from(SubscriptionEvent)
            .where(
                SubscriptionEvent.event_type == SubscriptionEventType.trial_started.value,
                SubscriptionEvent.created_at >= since_30d,
            )
        )
        or 0
    )
    activations_30d = (
        db.scalar(
            select(func.count())
            .select_from(SubscriptionEvent)
            .where(
                SubscriptionEvent.event_type == SubscriptionEventType.subscription_activated.value,
                SubscriptionEvent.created_at >= since_30d,
            )
        )
        or 0
    )
    conversion_rate_30d = (activations_30d / trials_started_30d * 100) if trials_started_30d else 0.0

    return BusinessMetrics(
        organizations_total=organizations_total,
        active_users_total=active_users_total,
        paying_organizations=paying_organizations,
        trial_organizations=trial_organizations,
        mrr=mrr,
        arr=arr,
        currency=currency,
        churn_rate_30d=round(churn_rate_30d, 2),
        conversion_rate_30d=round(conversion_rate_30d, 2),
        average_revenue_per_organization=round(average_revenue_per_organization, 2),
    )
