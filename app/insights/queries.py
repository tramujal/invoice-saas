"""Bounded, org-scoped queries for the dashboard insights engine
(app/insights/engine.py) that don't already exist in
app/routers/dashboard.py or app/assistant_context.py.

Every function here takes organization_id explicitly and filters on it,
and is a single query -- never a Python loop issuing one query per row --
matching every other module in this codebase.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, Invoice
from app.payment_status import PaymentStatus

# Defensive ceiling -- realistically very few SMBs have more than this many
# simultaneously overdue invoices at once; bounds the query even in a
# pathological case rather than fetching an unbounded row set. The engine
# derives amount-by-currency, oldest, and largest all from this one result
# set, so one generous limit here is enough for all three.
OVERDUE_DETAIL_LIMIT = 200


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
    oldest, and largest per currency all from this single result set."""
    rows = db.scalars(
        select(Invoice)
        .options(selectinload(Invoice.customer))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.payment_status == PaymentStatus.overdue.value,
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
