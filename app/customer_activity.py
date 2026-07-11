"""Shared "when was this customer last invoiced" data, used by both the AI
assistant's business context (app/assistant_context.py) and the dashboard
insights engine (app/insights/engine.py) — one query, two different
prioritizations layered on top by each caller (the assistant highlights
never-invoiced customers first; the insights engine prioritizes previously
active customers who've gone quiet, since that's a stronger revenue-risk
signal than a lead who was never converted).
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Invoice


def get_last_invoice_at_by_customer(db: Session, organization_id: str) -> dict[str, datetime]:
    """Returns {customer_id: most recent Invoice.created_at}, only for
    customers with at least one invoice in this organization — a customer
    with no entry has never been invoiced. Always UTC-aware: SQLite returns
    naive datetimes even for DateTime(timezone=True) columns (Postgres
    returns aware ones), and every timestamp in this table is written as
    UTC regardless of backend (see dashboard.py's own note on this), so
    normalization happens once here rather than in every caller.
    """
    rows = db.execute(
        select(Invoice.customer_id, func.max(Invoice.created_at))
        .where(
            Invoice.organization_id == organization_id,
            Invoice.customer_id.is_not(None),
        )
        .group_by(Invoice.customer_id)
    ).all()

    result: dict[str, datetime] = {}
    for customer_id, last_at in rows:
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        result[customer_id] = last_at
    return result
