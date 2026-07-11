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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.ai.limits import AI_MAX_CONTEXT_CHARS
from app.currency import format_amount
from app.invoice_numbering import format_invoice_number
from app.localization import get_language, t
from app.models import Customer, Invoice, Organization
from app.payment_status import PaymentStatus
from app.routers.dashboard import get_dashboard_analytics_data, get_dashboard_summary
from app.schemas import DashboardAnalyticsResponse, DashboardResponse

OVERDUE_INVOICES_LIMIT = 10
STALE_CUSTOMERS_LIMIT = 10
STALE_CUSTOMER_DAYS = 60


@dataclass
class OverdueInvoiceInfo:
    invoice_number: str
    customer_name: str | None
    total: Decimal
    currency_code: str
    created_at: datetime


@dataclass
class StaleCustomerInfo:
    name: str
    days_since_last_invoice: int | None  # None => never invoiced


@dataclass
class BusinessContext:
    organization_name: str
    language: str
    dashboard: DashboardResponse
    analytics: DashboardAnalyticsResponse
    overdue_invoice_list: list[OverdueInvoiceInfo]
    stale_customers: list[StaleCustomerInfo]


def _overdue_invoice_list(db: Session, organization_id: str) -> list[OverdueInvoiceInfo]:
    rows = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.payment_status == PaymentStatus.overdue.value,
        )
        .order_by(Invoice.created_at.asc())
        .limit(OVERDUE_INVOICES_LIMIT)
    ).all()
    return [
        OverdueInvoiceInfo(
            invoice_number=format_invoice_number(inv.invoice_number),
            customer_name=inv.customer_name,
            total=inv.total,
            currency_code=inv.currency_code,
            created_at=inv.created_at,
        )
        for inv in rows
    ]


def _stale_customers(db: Session, organization_id: str, now: datetime) -> list[StaleCustomerInfo]:
    last_invoice_at = dict(
        db.execute(
            select(Invoice.customer_id, func.max(Invoice.created_at))
            .where(
                Invoice.organization_id == organization_id,
                Invoice.customer_id.is_not(None),
            )
            .group_by(Invoice.customer_id)
        ).all()
    )
    customers = db.scalars(
        select(Customer).where(Customer.organization_id == organization_id)
    ).all()

    cutoff = now - timedelta(days=STALE_CUSTOMER_DAYS)
    stale: list[StaleCustomerInfo] = []
    for customer in customers:
        last_at = last_invoice_at.get(customer.id)
        # SQLite returns naive datetimes even for DateTime(timezone=True)
        # columns (Postgres returns aware ones) — normalize to UTC-aware
        # before comparing, since every timestamp in this table is written
        # as UTC regardless of backend (see dashboard.py's own note on this).
        if last_at is not None and last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
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


def build_business_context(db: Session, organization_id: str) -> BusinessContext:
    """Assumes the caller has already authorized the request (require_org_member
    + require_verified_email) — this function does not re-check
    authorization itself, matching get_dashboard_summary/
    get_dashboard_analytics_data's own contract."""
    organization = db.get(Organization, organization_id)
    now = datetime.now(timezone.utc)

    return BusinessContext(
        organization_name=organization.name if organization else "",
        language=get_language(organization),
        dashboard=get_dashboard_summary(db, organization_id),
        analytics=get_dashboard_analytics_data(db, organization_id),
        overdue_invoice_list=_overdue_invoice_list(db, organization_id),
        stale_customers=_stale_customers(db, organization_id, now),
    )


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
