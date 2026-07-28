"""Thin analytics-layer wrapper around app.product_analytics -- top
products/services is already a clean, tenant-scoped, well-tested query
module; this file re-exposes it under the analytics calculator namespace
(so AnalyticsService and callers of app.analytics.calculators have one
consistent import surface) rather than copying its SQL. See
app.product_analytics's own module docstring for the underlying query
semantics (revenue = booked, not collected; only line items linked to a
catalog product are attributed).
"""

from sqlalchemy.orm import Session

from app.product_analytics import ProductRevenue, get_revenue_by_product

__all__ = ["ProductRevenue", "get_revenue_by_product", "get_top_products"]

TOP_PRODUCTS_DEFAULT_LIMIT = 5


def get_top_products(
    db: Session, organization_id: str, *, limit: int = TOP_PRODUCTS_DEFAULT_LIMIT
) -> list[ProductRevenue]:
    """Top products/services by revenue, ranked independently within each
    (currency, product_type) pair -- relocated ranking logic from
    app.routers.dashboard.get_dashboard_analytics_data, built on top of
    app.product_analytics.get_revenue_by_product's existing all-time
    query (all-time only, not window-filterable today -- that query
    doesn't discriminate by Invoice.created_at at all; see that module).
    A single "top N by currency" cut would let a business's many services
    crowd out its one product entirely, so ranking happens per (currency,
    type) pair instead, matching the original dashboard behavior exactly.
    """
    rows = get_revenue_by_product(db, organization_id)
    rows_by_key: dict[tuple[str, str], list[ProductRevenue]] = {}
    for row in rows:
        rows_by_key.setdefault((row.currency_code, row.product_type), []).append(row)

    top: list[ProductRevenue] = []
    for key in sorted(rows_by_key):
        ranked = sorted(rows_by_key[key], key=lambda r: r.revenue, reverse=True)
        top.extend(ranked[:limit])
    return top
