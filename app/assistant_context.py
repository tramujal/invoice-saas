"""Builds the bounded, tenant-scoped business summary fed to the AI
assistant — see app/routers/assistant.py.

Reuses app.routers.dashboard's get_dashboard_summary/get_dashboard_analytics_data
verbatim (never a second, potentially-drifting computation of the same
numbers), and adds exactly two new bounded queries that don't exist
anywhere else: an actual overdue-invoice list (the dashboard only exposes a
count) and customers not invoiced recently. Every query here takes
organization_id as an explicit, required argument and filters on it —
the same tenant-isolation pattern every other router already uses.

No SQL is ever generated from user input, and the model is never given
database access of its own — this module is the only thing that touches
the database on behalf of the assistant; the LLM only ever sees the text
this module produces.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.limits import AI_MAX_CONTEXT_CHARS
from app.currency import format_amount
from app.customer_activity import get_last_invoice_at_by_customer
from app.insights.queries import get_due_soon_invoice_details, get_overdue_invoice_details
from app.invoice_numbering import format_invoice_number
from app.localization import get_language, t
from app.membership_status import MembershipStatus
from app.models import Customer, InvoiceReminder, Organization, OrganizationMember
from app.permissions import Permission, roles_with_permission
from app.product_analytics import get_dormant_products
from app.quote_numbering import format_quote_number
from app.quote_analytics import (
    get_quote_pipeline_summary,
    get_quotes_expired,
    get_quotes_pending_response,
)
from app.reminder_status import ReminderStatus
from app.routers.dashboard import get_dashboard_analytics_data, get_dashboard_summary
from app.schemas import DashboardAnalyticsResponse, DashboardResponse
from app.team_analytics import (
    get_pending_invitations,
    get_recent_accepted_members,
    get_team_summary,
)

OVERDUE_INVOICES_LIMIT = 10
DUE_SOON_INVOICES_LIMIT = 10
STALE_CUSTOMERS_LIMIT = 10
STALE_CUSTOMER_DAYS = 60
REMINDER_SUMMARY_DAYS = 30
DORMANT_PRODUCTS_LIMIT = 10
DORMANT_PRODUCTS_DAYS = 90
QUOTES_PENDING_LIMIT = 10
QUOTES_EXPIRED_LIMIT = 10
TEAM_PENDING_INVITATIONS_LIMIT = 10
TEAM_RECENT_MEMBERS_LIMIT = 10


@dataclass
class OverdueInvoiceInfo:
    invoice_number: str
    customer_name: str | None
    total: Decimal
    currency_code: str
    created_at: datetime


@dataclass
class DueSoonInvoiceInfo:
    invoice_number: str
    customer_name: str | None
    total: Decimal
    currency_code: str
    due_date: date


@dataclass
class StaleCustomerInfo:
    name: str
    days_since_last_invoice: int | None  # None => never invoiced


@dataclass
class DormantProductInfo:
    name: str
    product_type: str
    days_since_last_sale: int


@dataclass
class QuoteInfo:
    quote_number: str
    customer_name: str | None
    total: Decimal
    currency_code: str


@dataclass
class TeamPendingInvitationInfo:
    email: str
    role: str


@dataclass
class TeamRecentMemberInfo:
    user_email: str
    role: str
    invited_by_email: str | None


@dataclass
class BusinessContext:
    organization_name: str
    language: str
    dashboard: DashboardResponse
    analytics: DashboardAnalyticsResponse
    overdue_invoice_list: list[OverdueInvoiceInfo]
    due_soon_invoice_list: list[DueSoonInvoiceInfo]
    stale_customers: list[StaleCustomerInfo]
    reminders_sent_recently: int
    dormant_products: list[DormantProductInfo]
    quotes_pending: list[QuoteInfo]
    quotes_expired: list[QuoteInfo]
    quote_acceptance_rate_percent: float | None
    team_size: int
    team_owners: list[str]
    team_admins: list[str]
    team_pending_invitations: list[TeamPendingInvitationInfo]
    team_recent_members: list[TeamRecentMemberInfo]


def _overdue_invoice_list(db: Session, organization_id: str) -> list[OverdueInvoiceInfo]:
    """Due-date-derived, via app.insights.queries -- the same source of
    truth the dashboard insights use, never a separate re-check of the
    raw stored payment_status column (see app.effective_status)."""
    details = get_overdue_invoice_details(db, organization_id)[:OVERDUE_INVOICES_LIMIT]
    return [
        OverdueInvoiceInfo(
            invoice_number=format_invoice_number(d.invoice_number),
            customer_name=d.customer_name,
            total=d.total,
            currency_code=d.currency_code,
            created_at=d.created_at,
        )
        for d in details
    ]


def _due_soon_invoice_list(db: Session, organization_id: str) -> list[DueSoonInvoiceInfo]:
    details = get_due_soon_invoice_details(db, organization_id)[:DUE_SOON_INVOICES_LIMIT]
    return [
        DueSoonInvoiceInfo(
            invoice_number=format_invoice_number(d.invoice_number),
            customer_name=d.customer_name,
            total=d.total,
            currency_code=d.currency_code,
            due_date=d.due_date,
        )
        for d in details
    ]


def _reminders_sent_recently(db: Session, organization_id: str, now: datetime) -> int:
    """One aggregate count only -- never itemized audit rows or email
    content -- matching this module's existing "bounded, compact summary,
    never a raw data export" contract."""
    cutoff = now - timedelta(days=REMINDER_SUMMARY_DAYS)
    return (
        db.scalar(
            select(func.count())
            .select_from(InvoiceReminder)
            .where(
                InvoiceReminder.organization_id == organization_id,
                InvoiceReminder.status == ReminderStatus.sent.value,
                InvoiceReminder.sent_at >= cutoff,
            )
        )
        or 0
    )


def _stale_customers(db: Session, organization_id: str, now: datetime) -> list[StaleCustomerInfo]:
    last_invoice_at = get_last_invoice_at_by_customer(db, organization_id)
    customers = db.scalars(
        select(Customer).where(Customer.organization_id == organization_id)
    ).all()

    cutoff = now - timedelta(days=STALE_CUSTOMER_DAYS)
    stale: list[StaleCustomerInfo] = []
    for customer in customers:
        last_at = last_invoice_at.get(customer.id)
        if last_at is None:
            stale.append(StaleCustomerInfo(name=customer.name, days_since_last_invoice=None))
        elif last_at < cutoff:
            stale.append(
                StaleCustomerInfo(
                    name=customer.name, days_since_last_invoice=(now - last_at).days
                )
            )

    # Never-invoiced customers first, then longest-stale first — both read
    # as "most in need of attention" first.
    stale.sort(key=lambda s: (s.days_since_last_invoice is not None, -(s.days_since_last_invoice or 0)))
    return stale[:STALE_CUSTOMERS_LIMIT]


def _dormant_products(db: Session, organization_id: str, now: datetime) -> list[DormantProductInfo]:
    """Products that have sold before but not recently -- "stopped
    selling," bounded the same way every other list in this module is.
    Reuses app.product_analytics.get_dormant_products, the same query the
    insights engine's dormant-product data-quality signal uses."""
    dormant = get_dormant_products(db, organization_id, now, DORMANT_PRODUCTS_DAYS)
    return [
        DormantProductInfo(name=product.name, product_type=product.type, days_since_last_sale=days)
        for product, days in dormant[:DORMANT_PRODUCTS_LIMIT]
    ]


def _quotes_pending(db: Session, organization_id: str) -> list[QuoteInfo]:
    details = get_quotes_pending_response(db, organization_id)[:QUOTES_PENDING_LIMIT]
    return [
        QuoteInfo(
            quote_number=format_quote_number(d.quote_number),
            customer_name=d.customer_name,
            total=d.total,
            currency_code=d.currency_code,
        )
        for d in details
    ]


def _quotes_expired(db: Session, organization_id: str) -> list[QuoteInfo]:
    details = get_quotes_expired(db, organization_id)[:QUOTES_EXPIRED_LIMIT]
    return [
        QuoteInfo(
            quote_number=format_quote_number(d.quote_number),
            customer_name=d.customer_name,
            total=d.total,
            currency_code=d.currency_code,
        )
        for d in details
    ]


def _team_context(
    db: Session, organization_id: str
) -> tuple[int, list[str], list[str], list[TeamPendingInvitationInfo], list[TeamRecentMemberInfo]]:
    """Returns (team_size, owner_emails, admin_emails, pending_invitations,
    recent_members) -- reuses app.team_analytics's shared queries, the
    same ones app.routers.dashboard and app.insights.engine's team
    insights use, so the assistant's answer to "how many members do we
    have" can never drift from what the dashboard shows. Bounded the same
    way every other list in this module is (max 10)."""
    summary = get_team_summary(db, organization_id)

    # "Owners" and "admins" here mean *capability*, not a specific role
    # name: owner-equivalent = holds organization.manage (the same
    # permission app.services.team's ownership invariants key off);
    # admin-equivalent = holds members.manage but not organization.manage,
    # so nobody is double-counted. A future custom role granted either
    # permission is correctly included with no change here.
    owner_roles = [r.value for r in roles_with_permission(Permission.organization_manage)]
    admin_roles = [
        r.value
        for r in roles_with_permission(Permission.members_manage)
        if r not in roles_with_permission(Permission.organization_manage)
    ]
    owner_and_admin_rows = db.scalars(
        select(OrganizationMember)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == MembershipStatus.active.value,
            OrganizationMember.role.in_(owner_roles + admin_roles),
        )
        .limit(2 * TEAM_RECENT_MEMBERS_LIMIT)
    ).all()
    owner_emails = [m.user_email for m in owner_and_admin_rows if m.role in owner_roles][
        :TEAM_RECENT_MEMBERS_LIMIT
    ]
    admin_emails = [m.user_email for m in owner_and_admin_rows if m.role in admin_roles][
        :TEAM_RECENT_MEMBERS_LIMIT
    ]

    pending = [
        TeamPendingInvitationInfo(email=inv.email, role=inv.role)
        for inv in get_pending_invitations(db, organization_id, TEAM_PENDING_INVITATIONS_LIMIT)
    ]
    recent = [
        TeamRecentMemberInfo(
            user_email=m.user_email, role=m.role, invited_by_email=m.invited_by_email
        )
        for m in get_recent_accepted_members(db, organization_id, limit=TEAM_RECENT_MEMBERS_LIMIT)
    ]

    return summary.total_members, owner_emails, admin_emails, pending, recent


def build_business_context(db: Session, organization_id: str) -> BusinessContext:
    """Assumes the caller has already authorized the request (require_org_member
    + require_verified_email) — this function does not re-check
    authorization itself, matching get_dashboard_summary/
    get_dashboard_analytics_data's own contract."""
    organization = db.get(Organization, organization_id)
    now = datetime.now(timezone.utc)
    team_size, owner_emails, admin_emails, pending_invitations, recent_members = _team_context(
        db, organization_id
    )

    return BusinessContext(
        organization_name=organization.name if organization else "",
        language=get_language(organization),
        dashboard=get_dashboard_summary(db, organization_id),
        analytics=get_dashboard_analytics_data(db, organization_id),
        overdue_invoice_list=_overdue_invoice_list(db, organization_id),
        due_soon_invoice_list=_due_soon_invoice_list(db, organization_id),
        stale_customers=_stale_customers(db, organization_id, now),
        reminders_sent_recently=_reminders_sent_recently(db, organization_id, now),
        dormant_products=_dormant_products(db, organization_id, now),
        quotes_pending=_quotes_pending(db, organization_id),
        quotes_expired=_quotes_expired(db, organization_id),
        quote_acceptance_rate_percent=get_quote_pipeline_summary(
            db, organization_id
        ).acceptance_rate_percent,
        team_size=team_size,
        team_owners=owner_emails,
        team_admins=admin_emails,
        team_pending_invitations=pending_invitations,
        team_recent_members=recent_members,
    )


def _append_team_section(lines: list[str], context: BusinessContext, language: str) -> None:
    lines.append("")
    lines.append(f"{t(language, 'assistant_team_heading')}:")
    lines.append(f"- {t(language, 'assistant_team_size_label')}: {context.team_size}")
    lines.append(
        f"- {t(language, 'assistant_team_owners_label')}: "
        + (", ".join(context.team_owners) if context.team_owners else "—")
    )
    lines.append(
        f"- {t(language, 'assistant_team_admins_label')}: "
        + (", ".join(context.team_admins) if context.team_admins else "—")
    )

    lines.append("")
    lines.append(f"{t(language, 'assistant_team_pending_invitations_heading')} (max {TEAM_PENDING_INVITATIONS_LIMIT}):")
    if not context.team_pending_invitations:
        lines.append(f"- {t(language, 'assistant_no_pending_invitations')}")
    for invitation in context.team_pending_invitations:
        lines.append(f"- {invitation.email} ({invitation.role})")

    lines.append("")
    lines.append(f"{t(language, 'assistant_team_recent_members_heading')} (max {TEAM_RECENT_MEMBERS_LIMIT}):")
    if not context.team_recent_members:
        lines.append(f"- {t(language, 'assistant_no_recent_members')}")
    for member in context.team_recent_members:
        invited_by = (
            f" ({t(language, 'assistant_invited_by_label')} {member.invited_by_email})"
            if member.invited_by_email
            else ""
        )
        lines.append(f"- {member.user_email} ({member.role}){invited_by}")


def format_business_context_as_text(context: BusinessContext) -> str:
    """Renders a bounded, compact, currency-safe plain-text summary — never
    a JSON dump of raw rows, and never large enough to approach a full
    database export. Reuses app.currency.format_amount for every amount and
    app.localization.t for every label, so this stays visually consistent
    with the PDF/dashboard the user already sees."""
    language = context.language
    lines: list[str] = []

    lines.append(f"{t(language, 'assistant_org_label')}: {context.organization_name}")

    if context.dashboard.total_invoices == 0 and context.dashboard.total_customers == 0:
        lines.append(t(language, "assistant_no_data_note"))
        # Team composition is independent of invoicing/customer activity --
        # a brand-new org with zero invoices can still answer "how many
        # members do we have?" -- so it renders even on this early return,
        # unlike the rest of the (invoice/customer-dependent) sections below.
        _append_team_section(lines, context, language)
        text = "\n".join(lines)
        return text[:AI_MAX_CONTEXT_CHARS]

    lines.append(
        f"{t(language, 'assistant_total_invoices_label')}: {context.dashboard.total_invoices}"
    )
    lines.append(
        f"{t(language, 'assistant_total_customers_label')}: {context.dashboard.total_customers}"
    )

    lines.append("")
    lines.append(f"{t(language, 'assistant_invoice_status_heading')}:")
    lines.append(f"- {t(language, 'status_pending')}: {context.dashboard.pending_invoices}")
    lines.append(f"- {t(language, 'status_paid')}: {context.dashboard.paid_invoices}")
    lines.append(f"- {t(language, 'status_overdue')}: {context.dashboard.overdue_invoices}")

    lines.append("")
    lines.append(f"{t(language, 'assistant_revenue_heading')}:")
    lines.append(f"({t(language, 'assistant_no_exchange_rate_note')})")
    if not context.dashboard.revenue_by_currency:
        lines.append(f"- {t(language, 'assistant_no_data_note')}")
    for rev in context.dashboard.revenue_by_currency:
        growth = (
            f", {t(language, 'assistant_growth_label')} {rev.revenue_growth_percent}%"
            if rev.revenue_growth_percent is not None
            else ""
        )
        lines.append(
            f"- {rev.currency_code}: {t(language, 'total_label')} "
            f"{format_amount(rev.total_revenue, rev.currency_code)}, "
            f"{t(language, 'assistant_this_month_label')} "
            f"{format_amount(rev.revenue_this_month, rev.currency_code)}, "
            f"{t(language, 'assistant_last_month_label')} "
            f"{format_amount(rev.revenue_last_month, rev.currency_code)}"
            f"{growth}"
        )

    lines.append("")
    lines.append(f"{t(language, 'assistant_overdue_invoices_heading')} (max {OVERDUE_INVOICES_LIMIT}):")
    if not context.overdue_invoice_list:
        lines.append(f"- {t(language, 'assistant_no_overdue_invoices')}")
    for inv in context.overdue_invoice_list:
        customer = inv.customer_name or t(language, "no_customer")
        lines.append(
            f"- {inv.invoice_number} | {customer} | "
            f"{format_amount(inv.total, inv.currency_code)} | "
            f"{inv.created_at.date().isoformat()}"
        )

    lines.append("")
    lines.append(f"{t(language, 'assistant_due_soon_invoices_heading')} (max {DUE_SOON_INVOICES_LIMIT}):")
    if not context.due_soon_invoice_list:
        lines.append(f"- {t(language, 'assistant_no_due_soon_invoices')}")
    for inv in context.due_soon_invoice_list:
        customer = inv.customer_name or t(language, "no_customer")
        lines.append(
            f"- {inv.invoice_number} | {customer} | "
            f"{format_amount(inv.total, inv.currency_code)} | "
            f"{inv.due_date.isoformat()}"
        )

    lines.append("")
    lines.append(
        t(language, "assistant_reminders_sent_label").format(
            count=context.reminders_sent_recently, days=REMINDER_SUMMARY_DAYS
        )
    )

    lines.append("")
    lines.append(f"{t(language, 'assistant_recent_invoices_heading')}:")
    if not context.dashboard.recent_invoices:
        lines.append(f"- {t(language, 'assistant_no_data_note')}")
    for inv in context.dashboard.recent_invoices:
        customer = inv.customer_name or t(language, "no_customer")
        status_label = t(language, f"status_{inv.payment_status.value}")
        lines.append(
            f"- {inv.invoice_number} | {customer} | {status_label} | "
            f"{format_amount(inv.total, inv.currency_code)} | "
            f"{inv.created_at.date().isoformat()}"
        )

    lines.append("")
    lines.append(f"{t(language, 'assistant_top_customers_heading')} (max 5 per currency):")
    if not context.dashboard.revenue_by_currency:
        lines.append(f"- {t(language, 'assistant_no_data_note')}")
    else:
        by_currency: dict[str, list[str]] = {}
        for row in context.analytics.top_customers:
            by_currency.setdefault(row.currency_code, []).append(
                f"{row.customer_name} ({format_amount(row.revenue, row.currency_code)})"
            )
        if not by_currency:
            lines.append(f"- {t(language, 'assistant_no_data_note')}")
        for currency_code in sorted(by_currency):
            lines.append(f"- {currency_code}: " + "; ".join(by_currency[currency_code]))

    lines.append("")
    lines.append(f"{t(language, 'assistant_top_products_heading')} (max 5 per currency):")
    products_by_currency: dict[str, list[str]] = {}
    services_by_currency: dict[str, list[str]] = {}
    for row in context.analytics.top_products_and_services:
        target = products_by_currency if row.product_type == "product" else services_by_currency
        target.setdefault(row.currency_code, []).append(
            f"{row.product_name} ({format_amount(row.revenue, row.currency_code)}, "
            f"{row.invoice_count} invoices)"
        )
    if not products_by_currency and not services_by_currency:
        lines.append(f"- {t(language, 'assistant_no_data_note')}")
    else:
        for currency_code in sorted(products_by_currency):
            lines.append(
                f"- {t(language, 'assistant_products_label')} {currency_code}: "
                + "; ".join(products_by_currency[currency_code])
            )
        for currency_code in sorted(services_by_currency):
            lines.append(
                f"- {t(language, 'assistant_services_label')} {currency_code}: "
                + "; ".join(services_by_currency[currency_code])
            )

    lines.append("")
    lines.append(
        f"{t(language, 'assistant_dormant_products_heading')} "
        f"({DORMANT_PRODUCTS_DAYS}+ days, max {DORMANT_PRODUCTS_LIMIT}):"
    )
    if not context.dormant_products:
        lines.append(f"- {t(language, 'assistant_no_dormant_products')}")
    for dormant in context.dormant_products:
        lines.append(f"- {dormant.name} — {t(language, 'assistant_days_since_last_sale').format(days=dormant.days_since_last_sale)}")

    lines.append("")
    lines.append(
        f"{t(language, 'assistant_stale_customers_heading')} "
        f"({STALE_CUSTOMER_DAYS}+ days, max {STALE_CUSTOMERS_LIMIT}):"
    )
    if not context.stale_customers:
        lines.append(f"- {t(language, 'assistant_no_stale_customers')}")
    for stale in context.stale_customers:
        detail = (
            t(language, "assistant_never_invoiced")
            if stale.days_since_last_invoice is None
            else t(language, "assistant_days_since_invoice").format(
                days=stale.days_since_last_invoice
            )
        )
        lines.append(f"- {stale.name} — {detail}")

    lines.append("")
    lines.append(f"{t(language, 'assistant_quotes_pending_heading')} (max {QUOTES_PENDING_LIMIT}):")
    if not context.quotes_pending:
        lines.append(f"- {t(language, 'assistant_no_quotes_pending')}")
    for quote in context.quotes_pending:
        customer = quote.customer_name or t(language, "no_customer")
        lines.append(f"- {quote.quote_number} | {customer} | {format_amount(quote.total, quote.currency_code)}")

    lines.append("")
    lines.append(f"{t(language, 'assistant_quotes_expired_heading')} (max {QUOTES_EXPIRED_LIMIT}):")
    if not context.quotes_expired:
        lines.append(f"- {t(language, 'assistant_no_quotes_expired')}")
    for quote in context.quotes_expired:
        customer = quote.customer_name or t(language, "no_customer")
        lines.append(f"- {quote.quote_number} | {customer} | {format_amount(quote.total, quote.currency_code)}")

    if context.quote_acceptance_rate_percent is not None:
        lines.append("")
        lines.append(
            t(language, "assistant_quote_conversion_rate_label").format(
                percentage=f"{context.quote_acceptance_rate_percent:.0f}"
            )
        )

    _append_team_section(lines, context, language)

    lines.append("")
    lines.append(f"{t(language, 'assistant_monthly_revenue_heading')}:")
    by_currency_months: dict[str, list[str]] = {}
    for point in context.analytics.monthly_revenue_by_currency:
        by_currency_months.setdefault(point.currency_code, []).append(
            f"{point.month}: {format_amount(point.revenue, point.currency_code)}"
        )
    if not by_currency_months:
        lines.append(f"- {t(language, 'assistant_no_data_note')}")
    for currency_code in sorted(by_currency_months):
        lines.append(f"- {currency_code}: " + ", ".join(by_currency_months[currency_code]))

    lines.append("")
    lines.append(f"{t(language, 'assistant_monthly_volume_heading')}:")
    lines.append(
        ", ".join(
            f"{point.month}: {point.invoice_count}"
            for point in context.analytics.monthly_summary
        )
    )

    text = "\n".join(lines)
    return text[:AI_MAX_CONTEXT_CHARS]
