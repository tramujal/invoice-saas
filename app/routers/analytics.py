"""GET /organizations/{organization_id}/analytics/kpis -- a single,
window-parameterized snapshot of the core KPI-engine metrics
(app.analytics.calculators), assembled entirely by AnalyticsService.

Deliberately the only route in this router for now: Phase 16A's job is
the analytics DOMAIN (AnalyticsService, calculators, time windows), not a
new dashboard UI -- see that phase's own completion report for the full
rationale. Every metric this endpoint returns is already independently
callable through AnalyticsService; adding a second, more specific route
later (e.g. a dedicated top-customers or revenue-trend endpoint) is a
router-only change, never a recomputation -- exactly the point of
building the calculator layer first.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics.service import AnalyticsService
from app.analytics.time_windows import TimeWindowKind, resolve_time_window
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import Organization, User
from app.permissions import Permission
from app.schemas import (
    AveragePaymentTimeResponse,
    CustomerRetentionResponse,
    InvoiceCountsResponse,
    KpiSnapshotResponse,
    RevenueBreakdownResponse,
    TimeWindowResponse,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/analytics", tags=["analytics"]
)


@router.get("/kpis", response_model=KpiSnapshotResponse)
def get_kpi_snapshot(
    organization_id: str,
    window: TimeWindowKind = Query(default=TimeWindowKind.current_month),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KpiSnapshotResponse:
    # Reuses the exact same permission this data already required when it
    # only lived behind the dashboard endpoints -- this is the same
    # figures, just newly queryable on their own by window.
    require_permission(current_user, organization_id, Permission.dashboard_view, db)

    if window == TimeWindowKind.custom:
        # A custom range needs explicit start/end query params this route
        # doesn't accept yet -- an honest 400 rather than silently
        # resolving to a meaningless default range.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "custom_window_not_supported",
                "message": "window=custom is not supported by this endpoint yet.",
            },
        )

    organization = db.get(Organization, organization_id)
    resolved = resolve_time_window(window, organization=organization)
    service = AnalyticsService(db, organization_id)

    invoice_counts = service.invoice_counts(resolved)
    retention = service.customer_retention()
    payment_time = service.average_payment_time()

    return KpiSnapshotResponse(
        window=TimeWindowResponse(kind=resolved.kind.value, start=resolved.start, end=resolved.end),
        invoice_counts=InvoiceCountsResponse(
            total=invoice_counts.total,
            pending=invoice_counts.pending,
            paid=invoice_counts.paid,
            overdue=invoice_counts.overdue,
        ),
        revenue_by_currency=service.revenue_by_currency(resolved),
        revenue_breakdown=[
            RevenueBreakdownResponse(
                currency_code=b.currency_code,
                total=b.total,
                paid=b.paid,
                outstanding=b.outstanding,
                overdue=b.overdue,
            )
            for b in service.revenue_breakdown(resolved)
        ],
        average_invoice_value=service.average_invoice_value(resolved),
        customer_growth=service.customer_growth(resolved),
        customer_retention=CustomerRetentionResponse(
            total_invoiced_customers=retention.total_invoiced_customers,
            repeat_customers=retention.repeat_customers,
            retention_rate_percent=retention.retention_rate_percent,
        ),
        quote_acceptance_rate_percent=service.quote_acceptance_rate(),
        average_payment_time=AveragePaymentTimeResponse(
            available=payment_time.available,
            average_days=payment_time.average_days,
            reason=payment_time.reason,
        ),
    )
