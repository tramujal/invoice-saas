"""GET .../financial-intelligence/* -- the Financial Dashboard's REST
surface (Phase 24.1, deterministic only: no forecasting, no AI
recommendations). Seven focused, independently-loadable endpoints rather
than one giant aggregate response -- the frontend's /analytics/financial
page fetches each section on its own, so one slow/failing section never
blocks the others from rendering.

Every endpoint is a thin two-liner: check Permission.financial_intelligence_view,
delegate to app.financial_intelligence.service (which itself re-checks the
plan capability before calling metrics.py/cashflow.py). No calculation
lives here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.billing.enforcement import CapabilityDeniedError
from app.database import get_db
from app.deps import get_current_user, require_permission
from app.financial_intelligence import service
from app.financial_intelligence.schemas import (
    CashflowCalendarResponse,
    CustomersSectionResponse,
    ExecutiveOverviewResponse,
    ProductsSectionResponse,
    QuotesSectionResponse,
    ReceivablesAgingResponse,
    RevenueTrendsResponse,
)
from app.models import User
from app.permissions import Permission

router = APIRouter(
    prefix="/organizations/{organization_id}/financial-intelligence", tags=["financial-intelligence"]
)


def _run(fn):
    try:
        return fn()
    except CapabilityDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.to_error_detail())


@router.get("/overview", response_model=ExecutiveOverviewResponse)
def get_overview(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExecutiveOverviewResponse:
    require_permission(current_user, organization_id, Permission.financial_intelligence_view, db)
    return _run(lambda: service.get_executive_overview(db, organization_id))


@router.get("/revenue-trends", response_model=RevenueTrendsResponse)
def get_revenue_trends(
    organization_id: str,
    months: int | None = Query(default=None, ge=2, le=36),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RevenueTrendsResponse:
    require_permission(current_user, organization_id, Permission.financial_intelligence_view, db)
    return _run(lambda: service.get_revenue_trends(db, organization_id, months=months))


@router.get("/receivables-aging", response_model=ReceivablesAgingResponse)
def get_receivables_aging(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReceivablesAgingResponse:
    require_permission(current_user, organization_id, Permission.financial_intelligence_view, db)
    return _run(lambda: service.get_receivables_aging(db, organization_id))


@router.get("/customers", response_model=CustomersSectionResponse)
def get_customers(
    organization_id: str,
    limit: int | None = Query(default=None, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CustomersSectionResponse:
    require_permission(current_user, organization_id, Permission.financial_intelligence_view, db)
    return _run(lambda: service.get_customers_section(db, organization_id, limit=limit))


@router.get("/products", response_model=ProductsSectionResponse)
def get_products(
    organization_id: str,
    limit: int | None = Query(default=None, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProductsSectionResponse:
    require_permission(current_user, organization_id, Permission.financial_intelligence_view, db)
    return _run(lambda: service.get_products_section(db, organization_id, limit=limit))


@router.get("/quotes", response_model=QuotesSectionResponse)
def get_quotes(
    organization_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuotesSectionResponse:
    require_permission(current_user, organization_id, Permission.financial_intelligence_view, db)
    return _run(lambda: service.get_quotes_section(db, organization_id))


@router.get("/cashflow-calendar", response_model=CashflowCalendarResponse)
def get_cashflow_calendar(
    organization_id: str,
    horizon_days: int = Query(default=30, ge=1, le=180),
    granularity: str = Query(default="week", pattern="^(day|week|month)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CashflowCalendarResponse:
    require_permission(current_user, organization_id, Permission.financial_intelligence_view, db)
    return _run(
        lambda: service.get_cashflow_calendar(
            db, organization_id, horizon_days=horizon_days, granularity=granularity
        )
    )
