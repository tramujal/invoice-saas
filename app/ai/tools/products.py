"""Product-name resolution for the AI assistant's create_invoice_draft
tool (see app/ai/tools/invoices.py). Mirrors _resolve_customer_by_name in
that same module exactly: case-insensitive substring match, scoped to one
organization, never guesses an ambiguous match.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.tools.types import AmbiguousProductError, ProductNotFoundError
from app.models import Product

_MAX_PRODUCT_MATCHES_TO_INSPECT = 20


def resolve_product_by_name(db: Session, organization_id: str, product_name: str) -> Product:
    """Only active products are searched -- matches the frontend
    autocomplete's own default (archived products are hidden unless a
    human explicitly asks to see them; the AI agent doesn't need that
    edge case). 0 matches -> ProductNotFoundError; 2+ ->
    AmbiguousProductError; exactly 1 -> resolved."""
    term = product_name.strip()
    if not term:
        raise ProductNotFoundError(product_name)

    matches = list(
        db.scalars(
            select(Product)
            .where(
                Product.organization_id == organization_id,
                Product.active.is_(True),
                Product.name.ilike(f"%{term}%"),
            )
            .order_by(Product.name.asc())
            .limit(_MAX_PRODUCT_MATCHES_TO_INSPECT)
        ).all()
    )
    if not matches:
        raise ProductNotFoundError(product_name)
    if len(matches) > 1:
        raise AmbiguousProductError([p.name for p in matches])
    return matches[0]
