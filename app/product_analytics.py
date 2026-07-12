"""Shared product-catalog analytics queries — used by both the dashboard
router (app/routers/dashboard.py) and the Business Insights engine
(app/insights/engine.py), matching the exact reuse rationale
get_pending_total_by_currency already established in dashboard.py: one
query, more than one caller, never duplicated.

"Revenue by product" always sums InvoiceLineItem.line_total regardless of
the invoice's payment_status — matching this app's existing convention
that "revenue" means booked/invoiced, not collected (see
get_dashboard_summary's own currency totals, which are computed the same
way). Only line items with a product_id are ever attributed to a product;
a manually-typed line with no product_id simply isn't part of any of
these queries — there's no catalog entry to attribute it to.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceLineItem, Product


@dataclass
class ProductRevenue:
    product_id: str
    product_name: str
    product_type: str
    currency_code: str
    revenue: Decimal
    invoice_count: int


def get_revenue_by_product(db: Session, organization_id: str) -> list[ProductRevenue]:
    """All-time revenue + usage count per (product, currency) — the base
    data both the dashboard's "top products/services" ranking and the
    insights engine's "top revenue product" signal are built from.
    invoice_count is a distinct-invoice count (a product used 3 times on
    the same invoice counts once), i.e. "how many invoices included this
    product" rather than "how many line items"."""
    rows = db.execute(
        select(
            Product.id,
            Product.name,
            Product.type,
            Invoice.currency_code,
            func.sum(InvoiceLineItem.line_total),
            func.count(func.distinct(Invoice.id)),
        )
        .select_from(InvoiceLineItem)
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .join(Product, Product.id == InvoiceLineItem.product_id)
        .where(
            Invoice.organization_id == organization_id,
            InvoiceLineItem.product_id.is_not(None),
        )
        .group_by(Product.id, Product.name, Product.type, Invoice.currency_code)
    ).all()

    return [
        ProductRevenue(
            product_id=product_id,
            product_name=name,
            product_type=type_,
            currency_code=currency_code,
            revenue=revenue,
            invoice_count=invoice_count,
        )
        for product_id, name, type_, currency_code, revenue, invoice_count in rows
    ]


def get_product_revenue_this_and_last_month(
    db: Session, organization_id: str, now: datetime
) -> dict[tuple[str, str], tuple[Decimal, Decimal]]:
    """{(product_id, currency_code): (this_month_revenue, last_month_revenue)}
    -- the same month-over-month shape app.routers.dashboard's revenue
    trend already uses, just grouped by product instead of currency alone,
    so the insights engine can reapply its exact existing growth-percent
    formula per product (see app.insights.engine._revenue_trend_insights)."""
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if this_month_start.month == 1:
        last_month_start = this_month_start.replace(year=this_month_start.year - 1, month=12)
    else:
        last_month_start = this_month_start.replace(month=this_month_start.month - 1)

    rows = db.execute(
        select(
            InvoiceLineItem.product_id,
            Invoice.currency_code,
            Invoice.created_at,
            InvoiceLineItem.line_total,
        )
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .where(
            Invoice.organization_id == organization_id,
            InvoiceLineItem.product_id.is_not(None),
            Invoice.created_at >= last_month_start,
        )
    ).all()

    totals: dict[tuple[str, str], list[Decimal]] = {}
    for product_id, currency_code, created_at, line_total in rows:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        key = (product_id, currency_code)
        if key not in totals:
            totals[key] = [Decimal("0"), Decimal("0")]
        if created_at >= this_month_start:
            totals[key][0] += line_total
        else:
            totals[key][1] += line_total

    return {key: (this_month, last_month) for key, (this_month, last_month) in totals.items()}


def get_products_never_invoiced(
    db: Session, organization_id: str, active_only: bool = True
) -> list[Product]:
    """Products with zero matching InvoiceLineItem rows -- a data-quality/
    catalog-hygiene signal, not a revenue one."""
    subquery = (
        select(InvoiceLineItem.product_id)
        .where(InvoiceLineItem.product_id.is_not(None))
        .distinct()
    )
    query = select(Product).where(
        Product.organization_id == organization_id,
        Product.id.not_in(subquery),
    )
    if active_only:
        query = query.where(Product.active.is_(True))
    return list(db.scalars(query).all())


def get_last_invoice_at_by_product(db: Session, organization_id: str) -> dict[str, datetime]:
    """{product_id: most recent Invoice.created_at that included it} --
    only for products with at least one sale. Mirrors
    app.customer_activity.get_last_invoice_at_by_customer's exact shape
    and UTC-normalization note (SQLite returns naive datetimes even for
    DateTime(timezone=True) columns)."""
    rows = db.execute(
        select(InvoiceLineItem.product_id, func.max(Invoice.created_at))
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .where(
            Invoice.organization_id == organization_id,
            InvoiceLineItem.product_id.is_not(None),
        )
        .group_by(InvoiceLineItem.product_id)
    ).all()

    result: dict[str, datetime] = {}
    for product_id, last_at in rows:
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        result[product_id] = last_at
    return result


def get_dormant_products(
    db: Session, organization_id: str, now: datetime, inactivity_days: int
) -> list[tuple[Product, int]]:
    """Active products that have sold at least once but not within the
    last `inactivity_days` days -- "stopped selling," distinct from
    products that never sold at all (see get_products_never_invoiced) and
    distinct from Product.active (catalog visibility, not sales activity).
    Returns (product, days_since_last_sale) pairs, longest-dormant first."""
    last_invoice_at = get_last_invoice_at_by_product(db, organization_id)
    if not last_invoice_at:
        return []

    cutoff = now - timedelta(days=inactivity_days)
    products = db.scalars(
        select(Product).where(
            Product.organization_id == organization_id,
            Product.active.is_(True),
            Product.id.in_(last_invoice_at.keys()),
        )
    ).all()

    dormant: list[tuple[Product, int]] = []
    for product in products:
        last_at = last_invoice_at[product.id]
        if last_at < cutoff:
            dormant.append((product, (now - last_at).days))

    dormant.sort(key=lambda pair: pair[1], reverse=True)
    return dormant
