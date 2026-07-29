"""Tests for app.billing.capabilities -- the reusable read-only
capability layer (Phase 17A). Pure boolean/quota logic is tested against
directly-constructed OrganizationCapabilities instances (no DB needed);
get_organization_capabilities itself is tested against a real
organization/plan/subscription to confirm the composition with
app.services.entitlements + app.services.organization_usage is wired
correctly end-to-end."""

from dataclasses import replace

from app.billing.capabilities import (
    OrganizationCapabilities,
    can_create_api_key,
    can_create_invoice,
    can_create_quote,
    can_create_webhook,
    can_use_ai,
    can_use_analytics,
    can_use_background_jobs,
    can_use_forecasting,
    get_organization_capabilities,
    remaining_api_keys,
    remaining_invoice_quota,
    remaining_quote_quota,
    remaining_users,
    remaining_webhooks,
)
from app.services.entitlements import Entitlements
from tests.factories import make_customer, make_invoice, make_organization, make_plan, make_subscription, make_user


def _caps(**entitlement_overrides) -> OrganizationCapabilities:
    defaults = dict(
        plan_id="plan_x",
        plan_code="x",
        plan_name="X",
        max_users=None,
        max_customers=None,
        max_products=None,
        max_invoices_per_month=None,
        max_quotes_per_month=None,
        max_ai_actions_per_month=None,
        storage_limit_mb=None,
        max_api_keys=None,
        max_webhooks=None,
        custom_branding_enabled=False,
        api_access_enabled=False,
        advanced_reports_enabled=False,
        analytics_enabled=False,
        forecasting_enabled=False,
        ai_enabled=False,
        background_jobs_enabled=False,
    )
    defaults.update(entitlement_overrides)
    entitlements = Entitlements(**defaults)
    return OrganizationCapabilities(
        entitlements=entitlements,
        usage_users=0,
        usage_customers=0,
        usage_products=0,
        usage_invoices=0,
        usage_quotes=0,
        usage_ai_actions=0,
        usage_api_keys=0,
        usage_webhooks=0,
    )


def test_can_use_flags_pass_through_entitlement_booleans():
    caps = _caps(analytics_enabled=True, forecasting_enabled=False, ai_enabled=True, background_jobs_enabled=False)

    assert can_use_analytics(caps) is True
    assert can_use_forecasting(caps) is False
    assert can_use_ai(caps) is True
    assert can_use_background_jobs(caps) is False


def test_remaining_is_none_for_an_unlimited_limit():
    caps = _caps(max_invoices_per_month=None)
    assert remaining_invoice_quota(caps) is None


def test_remaining_subtracts_usage_from_limit():
    caps = _caps(max_quotes_per_month=10)
    caps = replace(caps, usage_quotes=4)
    assert remaining_quote_quota(caps) == 6


def test_remaining_never_goes_negative_even_if_usage_exceeds_limit():
    """e.g. a plan downgrade after the fact leaves more usage than the
    new, smaller limit allows -- remaining must clamp at 0, not go
    negative."""
    caps = _caps(max_users=2)
    caps = replace(caps, usage_users=5)
    assert remaining_users(caps) == 0


def test_remaining_is_zero_when_limit_is_zero_and_unused():
    """limit=0 means the resource is entirely unavailable on this plan --
    distinct from limit=None (unlimited); remaining must be 0, not None."""
    caps = _caps(max_api_keys=0)
    assert remaining_api_keys(caps) == 0


def test_can_create_is_true_when_remaining_is_none_or_positive():
    unlimited = _caps(max_webhooks=None)
    assert can_create_webhook(unlimited) is True

    caps = _caps(max_webhooks=3)
    caps = replace(caps, usage_webhooks=2)
    assert can_create_webhook(caps) is True


def test_can_create_is_false_when_remaining_is_zero():
    caps = _caps(max_invoices_per_month=5)
    caps = replace(caps, usage_invoices=5)
    assert can_create_invoice(caps) is False

    unavailable = _caps(max_api_keys=0)
    assert can_create_api_key(unavailable) is False


def test_can_create_quote_reflects_remaining_quote_quota():
    exhausted = _caps(max_quotes_per_month=1)
    exhausted = replace(exhausted, usage_quotes=1)
    assert can_create_quote(exhausted) is False


def test_get_organization_capabilities_composes_entitlements_and_live_usage(db_session):
    plan = make_plan(
        db_session,
        code="caps-integration-plan",
        max_invoices_per_month=2,
        max_customers=None,
        ai_enabled=True,
    )
    organization = make_organization(db_session, name="Capabilities Co")
    make_subscription(db_session, organization, plan=plan)
    actor = make_user(db_session, email="caps-actor@example.com")
    customer = make_customer(db_session, organization)
    make_invoice(db_session, organization, actor, customer=customer)

    caps = get_organization_capabilities(db_session, organization.id)

    assert caps.entitlements.plan_id == plan.id
    assert caps.usage_invoices == 1
    assert remaining_invoice_quota(caps) == 1
    assert can_create_invoice(caps) is True
    assert can_use_ai(caps) is True
    assert can_use_analytics(caps) is False
