"""Tests for Phase 18.1's provider-customer caching --
app.models.ProviderCustomer + BillingService._get_or_create_provider_customer,
used internally by start_checkout. Exercises against FakeBillingProvider
only -- no Stripe awareness anywhere in this file."""

from sqlalchemy import select

from app.billing.service import BillingService
from app.billing_period import BillingPeriod
from app.models import ProviderCustomer
from tests.billing.fakes import FakeBillingProvider
from tests.factories import make_organization, make_plan, make_subscription, make_user


def _provider_customer_row(db_session, organization_id: str, provider_name: str) -> ProviderCustomer | None:
    return db_session.scalar(
        select(ProviderCustomer).where(
            ProviderCustomer.organization_id == organization_id,
            ProviderCustomer.provider_name == provider_name,
        )
    )


def test_first_checkout_creates_and_persists_a_provider_customer(db_session):
    organization = make_organization(db_session, name="Reuse First Co")
    subscription = make_subscription(db_session, organization)
    plan = make_plan(db_session, code="reuse-first-plan", sort_order=1)
    actor = make_user(db_session, email="reuse-first-actor@example.com")
    provider = FakeBillingProvider()

    BillingService(db_session, provider=provider).start_checkout(
        subscription,
        plan,
        BillingPeriod.monthly,
        actor=actor,
        success_url="https://app.test/success",
        cancel_url="https://app.test/cancel",
    )

    assert len(provider.create_customer_calls) == 1
    row = _provider_customer_row(db_session, organization.id, "fake")
    assert row is not None
    assert row.provider_customer_id == "cus_fake_1"


def test_second_checkout_reuses_the_cached_customer(db_session):
    organization = make_organization(db_session, name="Reuse Second Co")
    subscription = make_subscription(db_session, organization)
    plan_a = make_plan(db_session, code="reuse-second-plan-a", sort_order=1)
    plan_b = make_plan(db_session, code="reuse-second-plan-b", sort_order=2)
    actor = make_user(db_session, email="reuse-second-actor@example.com")
    provider = FakeBillingProvider()
    service = BillingService(db_session, provider=provider)

    service.start_checkout(
        subscription, plan_a, BillingPeriod.monthly, actor=actor,
        success_url="https://app.test/success", cancel_url="https://app.test/cancel",
    )
    service.start_checkout(
        subscription, plan_b, BillingPeriod.yearly, actor=actor,
        success_url="https://app.test/success", cancel_url="https://app.test/cancel",
    )

    # Only ONE provider customer was ever created, despite two checkouts.
    assert len(provider.create_customer_calls) == 1
    rows = db_session.scalars(
        select(ProviderCustomer).where(ProviderCustomer.organization_id == organization.id)
    ).all()
    assert len(rows) == 1
    # Both checkout sessions used the same customer_reference.
    assert (
        provider.create_checkout_session_calls[0].customer_reference
        == provider.create_checkout_session_calls[1].customer_reference
        == "cus_fake_1"
    )


def test_different_organizations_get_different_cached_customers(db_session):
    org_a = make_organization(db_session, name="Reuse Org A")
    org_b = make_organization(db_session, name="Reuse Org B")
    sub_a = make_subscription(db_session, org_a)
    sub_b = make_subscription(db_session, org_b)
    plan = make_plan(db_session, code="reuse-multi-org-plan", sort_order=1)
    actor = make_user(db_session, email="reuse-multi-org-actor@example.com")
    provider = FakeBillingProvider()
    service = BillingService(db_session, provider=provider)

    service.start_checkout(
        sub_a, plan, BillingPeriod.monthly, actor=actor,
        success_url="https://app.test/success", cancel_url="https://app.test/cancel",
    )
    service.start_checkout(
        sub_b, plan, BillingPeriod.monthly, actor=actor,
        success_url="https://app.test/success", cancel_url="https://app.test/cancel",
    )

    assert len(provider.create_customer_calls) == 2
    row_a = _provider_customer_row(db_session, org_a.id, "fake")
    row_b = _provider_customer_row(db_session, org_b.id, "fake")
    assert row_a.provider_customer_id != row_b.provider_customer_id


def test_concurrent_race_recovers_gracefully_and_returns_the_winning_row(db_session):
    """Simulates two requests racing to create the first ProviderCustomer
    row for the same organization: a competing row is inserted directly
    (standing in for a second, concurrent BillingService instance/session
    that won the race) between this call's own cache-miss check and its
    own INSERT. The UNIQUE(organization_id, provider_name) constraint
    then rejects this call's insert; it must recover by rolling back and
    reading the winner's row, never raising, never leaving the session in
    a broken state."""
    organization = make_organization(db_session, name="Reuse Race Co")
    subscription = make_subscription(db_session, organization)
    plan = make_plan(db_session, code="reuse-race-plan", sort_order=1)
    actor = make_user(db_session, email="reuse-race-actor@example.com")
    provider = FakeBillingProvider()
    service = BillingService(db_session, provider=provider)

    original_create_customer = provider.create_customer

    def create_customer_and_let_a_competitor_win(*, organization_id, email, name):
        # Stand in for a concurrent request's session committing a row
        # for this exact (organization_id, provider_name) first, right
        # after our own cache-miss check already ran but before our own
        # INSERT.
        db_session.add(
            ProviderCustomer(
                organization_id=organization_id,
                provider_name="fake",
                provider_customer_id="cus_fake_competitor",
            )
        )
        db_session.commit()
        return original_create_customer(organization_id=organization_id, email=email, name=name)

    provider.create_customer = create_customer_and_let_a_competitor_win

    session = service.start_checkout(
        subscription, plan, BillingPeriod.monthly, actor=actor,
        success_url="https://app.test/success", cancel_url="https://app.test/cancel",
    )

    # The call succeeded and used the WINNING (competitor's) customer id,
    # not the one its own provider.create_customer call produced.
    assert session.url.startswith("https://fake-provider.test/checkout/")
    checkout_request = provider.create_checkout_session_calls[0]
    assert checkout_request.customer_reference == "cus_fake_competitor"

    rows = db_session.scalars(
        select(ProviderCustomer).where(ProviderCustomer.organization_id == organization.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].provider_customer_id == "cus_fake_competitor"

    # The session is healthy afterward -- a later, unrelated commit still works.
    db_session.commit()
