"""Bounded, org-scoped queries for the dashboard insights engine
(app/insights/engine.py) that don't already exist in
app/routers/dashboard.py or app/assistant_context.py.

Every function here takes organization_id explicitly and filters on it,
and is a single query -- never a Python loop issuing one query per row --
matching every other module in this codebase.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, Invoice, Organization
from app.org_time import get_organization_today
from app.payment_status import PaymentStatus

# Defensive ceiling -- realistically very few SMBs have more than this many
# simultaneously overdue invoices at once; bounds the query even in a
# pathological case rather than fetching an unbounded row set. The engine
# derives amount-by-currency, oldest, and largest all from this one result
# set, so one generous limit here is enough for all three.
OVERDUE_DETAIL_LIMIT = 200

# How many days ahead counts as "due soon" for the due_soon insight.
DUE_SOON_WINDOW_DAYS = 7
DUE_SOON_DETAIL_LIMIT = 200


@dataclass
class OverdueInvoiceDetail:
    invoice_number: int
    invoice_id: str
    customer_name: str | None
    total: Decimal
    currency_code: str
    created_at: datetime


def get_overdue_invoice_details(
    db: Session, organization_id: str
) -> list[OverdueInvoiceDetail]:
    """All (bounded) overdue invoices for this org, oldest first, with
    their customer eager-loaded -- the caller derives amount-by-currency,
    oldest, and largest per currency all from this single result set.

    "Overdue" here is due-date-derived (due_date < the organization's
    local today, and not paid) -- the same source of truth every other
    surface uses (see app.effective_status) -- never the raw, manually-set
    payment_status column. An invoice with no due_date on file (every
    historical invoice) is never counted here even if its stored
    payment_status happens to say "overdue" -- see
    get_invoices_missing_due_date_count for surfacing those separately, as
    a data-quality signal instead.
    """
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    rows = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.due_date.is_not(None),
            Invoice.due_date < today_local,
            Invoice.payment_status != PaymentStatus.paid.value,
        )
        .order_by(Invoice.created_at.asc())
        .limit(OVERDUE_DETAIL_LIMIT)
    ).all()
    details = []
    for inv in rows:
        created_at = inv.created_at
        # SQLite returns naive datetimes even for DateTime(timezone=True)
        # columns (Postgres returns aware ones) -- normalize once here,
        # matching app/customer_activity.py's identical note.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        details.append(
            OverdueInvoiceDetail(
                invoice_number=inv.invoice_number,
                invoice_id=inv.id,
                customer_name=inv.customer_name,
                total=inv.total,
                currency_code=inv.currency_code,
                created_at=created_at,
            )
        )
    return details


@dataclass
class DueSoonInvoiceDetail:
    invoice_number: int
    invoice_id: str
    customer_name: str | None
    total: Decimal
    currency_code: str
    due_date: date


def get_due_soon_invoice_details(
    db: Session, organization_id: str
) -> list[DueSoonInvoiceDetail]:
    """Unpaid invoices due within the next DUE_SOON_WINDOW_DAYS days
    (inclusive of due today), soonest first -- a distinct, smaller-urgency
    signal from "already overdue" above."""
    organization = db.get(Organization, organization_id)
    today_local = get_organization_today(organization)
    window_end = today_local + timedelta(days=DUE_SOON_WINDOW_DAYS)
    rows = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.due_date.is_not(None),
            Invoice.due_date >= today_local,
            Invoice.due_date <= window_end,
            Invoice.payment_status != PaymentStatus.paid.value,
        )
        .order_by(Invoice.due_date.asc())
        .limit(DUE_SOON_DETAIL_LIMIT)
    ).all()
    return [
        DueSoonInvoiceDetail(
            invoice_number=inv.invoice_number,
            invoice_id=inv.id,
            customer_name=inv.customer_name,
            total=inv.total,
            currency_code=inv.currency_code,
            due_date=inv.due_date,
        )
        for inv in rows
    ]


def get_invoices_missing_due_date_count(db: Session, organization_id: str) -> int:
    """Every historical invoice created before this feature existed, plus
    any new invoice deliberately created without one -- surfaced as a
    data-quality signal (see _data_quality_insight), never miscounted as
    overdue."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(
                Invoice.organization_id == organization_id,
                Invoice.due_date.is_(None),
            )
        )
        or 0
    )


def get_invoices_without_customer_count(db: Session, organization_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(
                Invoice.organization_id == organization_id,
                Invoice.customer_id.is_(None),
            )
        )
        or 0
    )


def get_customers_missing_phone_count(db: Session, organization_id: str) -> int:
    # Customer.email is NOT NULL at the DB level in this schema (every
    # customer requires a real email at creation), so "missing email" is
    # never a real condition -- phone (which defaults to "") is the
    # meaningful data-quality gap to surface here.
    return (
        db.scalar(
            select(func.count())
            .select_from(Customer)
            .where(
                Customer.organization_id == organization_id,
                Customer.phone == "",
            )
        )
        or 0
    )
