"""app.analytics.calculators.products/quotes are thin, deliberately
untested-twice wrappers around app.product_analytics/app.quote_analytics
(already covered by their own test suites) -- these tests only confirm
the wrapper wiring itself: ranking-within-currency-and-type for products,
and pass-through delegation for quotes. Not a re-test of the underlying
query semantics.
"""

from decimal import Decimal

from app.analytics.calculators.products import get_top_products
from app.analytics.calculators.quotes import (
    get_quote_acceptance_rate,
    get_quote_pipeline,
)
from tests.factories import make_invoice, make_org_with_owner, make_product, make_quote


class TestGetTopProducts:
    def test_empty_dataset(self, db_session):
        org = make_org_with_owner(db_session, email="top-prod-empty@example.com")
        assert get_top_products(db_session, org.organization.id) == []

    def test_ranked_within_currency_and_type(self, db_session):
        from app.schemas import InvoiceLineItemCreate

        org = make_org_with_owner(db_session, email="top-prod@example.com")
        product = make_product(db_session, org.organization, name="Widget", unit_price=Decimal("50.00"))
        make_invoice(
            db_session,
            org.organization,
            org.user,
            line_items=[
                InvoiceLineItemCreate(
                    description="Widget",
                    quantity=Decimal("2"),
                    unit_price=Decimal("50.00"),
                    product_id=product.id,
                )
            ],
        )

        top = get_top_products(db_session, org.organization.id)
        assert len(top) == 1
        assert top[0].product_id == product.id
        assert top[0].revenue == Decimal("100.00")


class TestQuoteWrappers:
    def test_acceptance_rate_none_when_no_decided_quotes(self, db_session):
        org = make_org_with_owner(db_session, email="quote-wrap@example.com")
        make_quote(db_session, org.organization, org.user)
        assert get_quote_acceptance_rate(db_session, org.organization.id) is None

    def test_pipeline_delegates_to_quote_analytics(self, db_session):
        org = make_org_with_owner(db_session, email="quote-pipeline-wrap@example.com")
        make_quote(db_session, org.organization, org.user)
        pipeline = get_quote_pipeline(db_session, org.organization.id)
        assert pipeline.counts_by_status["draft"] == 1
