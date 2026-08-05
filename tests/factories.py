"""Test data builders.

Plain functions, not a factory-class DSL -- this repo has no existing
factory_boy/faker precedent and the domain is small enough that explicit
functions stay readable. Every factory takes the test's `db_session`
explicitly (no hidden global state). Business objects with real
invariants (invoices, quotes, invitations) go through the actual
service-layer functions rather than being constructed as bare ORM rows,
so totals/numbering/token-hashing are always correct for free and tests
exercise real business logic, not a parallel reimplementation of it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.billing_period import BillingPeriod
from app.membership_role import InvitationRole, MembershipRole
from app.payment_status import PaymentStatus
from app.models import (
    Customer,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Plan,
    Product,
    Subscription,
    User,
)
from app.schemas import CurrencyCode, InvoiceLineItemCreate, QuoteLineItemCreate
from app.security import create_access_token, hash_password
from app.services.invoices import create_invoice_record
from app.services.quotes import create_quote_record
from app.services.team import invite_member_record
from app.subscription_status import SubscriptionStatus


def make_user(db, *, email: str = "user@example.com", verified: bool = True) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("Correct-Horse-1"),
        email_verified_at=datetime.now(timezone.utc) if verified else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_organization(db, *, name: str = "Acme Inc") -> Organization:
    """Every organization in this app owns exactly one Subscription (see
    app.models.Subscription's own docstring -- it's the resolved source
    of truth for entitlements as of Phase 17A, not Organization.plan_id).
    A bare direct ORM insert here (not going through
    app.billing.service.BillingService.create_subscription, which is
    registration's own real path) is deliberately simple/minimal, matching
    every other factory in this module -- tests that need a specific
    subscription status/plan/trial should call make_subscription() below
    afterward, which replaces this default one."""
    organization = Organization(name=name)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    make_subscription(db, organization)
    return organization


def make_subscription(
    db,
    organization: Organization,
    *,
    plan: Plan | None = None,
    status: SubscriptionStatus = SubscriptionStatus.active,
    billing_period: BillingPeriod = BillingPeriod.monthly,
    trial_start=None,
    trial_end=None,
    current_period_start=None,
    current_period_end=None,
    cancel_at_period_end: bool = False,
    provider_name: str | None = None,
    provider_reference: str | None = None,
) -> Subscription:
    """Creates (replacing any existing one -- an organization has at most
    one) a Subscription with the given fields, for tests that need a
    specific status/plan/trial/period state rather than the plain active-
    on-the-organization's-current-plan default make_organization() sets
    up automatically. provider_name/provider_reference default to None
    (not provider-attached) -- pass both for tests exercising Phase SEC2
    (C3)'s provider-sync behavior."""
    existing = db.scalar(
        select(Subscription).where(Subscription.organization_id == organization.id)
    )
    if existing is not None:
        db.delete(existing)
        db.flush()

    now = datetime.now(timezone.utc)
    subscription = Subscription(
        organization_id=organization.id,
        plan_id=plan.id if plan is not None else organization.plan_id,
        status=status.value,
        billing_period=billing_period.value,
        trial_start=trial_start,
        trial_end=trial_end,
        current_period_start=current_period_start or now,
        current_period_end=current_period_end or (now + timedelta(days=30)),
        cancel_at_period_end=cancel_at_period_end,
        provider_name=provider_name,
        provider_reference=provider_reference,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def make_plan(
    db,
    *,
    code: str,
    name: str = "Test Plan",
    sort_order: int = 0,
    is_active: bool = True,
    **overrides,
) -> Plan:
    """A custom Plan row for tests exercising upgrade/downgrade (which
    classify by sort_order, never by code/name -- see
    app.billing.service.BillingService) or plan-CRUD scenarios that
    shouldn't touch the four seeded built-in plans."""
    plan = Plan(code=code, name=name, sort_order=sort_order, is_active=is_active, **overrides)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def make_membership(
    db,
    user: User,
    organization: Organization,
    *,
    role: MembershipRole = MembershipRole.member,
) -> OrganizationMember:
    membership = OrganizationMember(
        user_id=user.id, organization_id=organization.id, role=role.value
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


@dataclass
class OrgWithOwner:
    organization: Organization
    user: User
    membership: OrganizationMember

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(self.user.id)}"}


def make_org_with_owner(
    db, *, email: str = "owner@example.com", org_name: str = "Acme Inc"
) -> OrgWithOwner:
    user = make_user(db, email=email)
    organization = make_organization(db, name=org_name)
    membership = make_membership(db, user, organization, role=MembershipRole.owner)
    return OrgWithOwner(organization=organization, user=user, membership=membership)


def make_org_with_owner_on_plan(
    db, *, email: str = "owner@example.com", org_name: str = "Acme Inc", **plan_overrides
) -> OrgWithOwner:
    """Same as make_org_with_owner, but immediately replaces the auto-
    created Free-tier subscription with one on a custom plan -- for
    tests that need a specific capability/limit enabled (Phase 17B:
    analytics_enabled, forecasting_enabled, ai_enabled,
    background_jobs_enabled, max_api_keys, max_webhooks, ...) rather than
    the Free tier's own restrictive defaults. `plan_overrides` are passed
    straight through to make_plan, e.g. make_org_with_owner_on_plan(db,
    analytics_enabled=True)."""
    owner = make_org_with_owner(db, email=email, org_name=org_name)
    plan = make_plan(db, code=f"test-plan-{owner.organization.id}", **plan_overrides)
    make_subscription(db, owner.organization, plan=plan)
    return owner


def make_member_in_org(
    db,
    organization: Organization,
    *,
    email: str = "member@example.com",
    role: MembershipRole = MembershipRole.member,
) -> OrgWithOwner:
    """Same shape as make_org_with_owner, but joins an *existing*
    organization instead of creating a new one -- for multi-member/
    permission-matrix tests."""
    user = make_user(db, email=email)
    membership = make_membership(db, user, organization, role=role)
    return OrgWithOwner(organization=organization, user=user, membership=membership)


def make_customer(
    db,
    organization: Organization,
    *,
    name: str = "Test Customer",
    email: str = "customer@example.com",
    phone: str = "",
    tax_id: str = "",
) -> Customer:
    customer = Customer(
        organization_id=organization.id, name=name, email=email, phone=phone, tax_id=tax_id
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


def make_product(
    db,
    organization: Organization,
    *,
    name: str = "Consulting",
    unit_price: Decimal = Decimal("100.00"),
    currency_code: str = "USD",
) -> Product:
    product = Product(
        organization_id=organization.id,
        name=name,
        default_unit_price=unit_price,
        currency_code=currency_code,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def make_invoice(
    db,
    organization: Organization,
    actor: User,
    *,
    customer: Customer | None = None,
    line_items: list[InvoiceLineItemCreate] | None = None,
    tax_rate: Decimal = Decimal("0"),
    due_date=None,
    currency_code: CurrencyCode | None = CurrencyCode.USD,
):
    line_items = line_items or [
        InvoiceLineItemCreate(description="Line 1", quantity=Decimal("1"), unit_price=Decimal("100.00"))
    ]
    return create_invoice_record(
        db,
        organization.id,
        actor,
        customer,
        currency_code,
        line_items,
        tax_rate,
        due_date=due_date,
    )


def mark_invoice_paid(db, invoice, *, paid_at: datetime | None = None) -> None:
    """Test-only shortcut that sets payment_status/paid_at directly,
    bypassing update_invoice_payment_status_record (and therefore its
    emit_event side effects) -- used to build deterministic
    payment-delay history for app.financial_intelligence tests, where a
    test needs many invoices paid on specific, backdated timestamps
    rather than "now". Real payment-status transitions in the app always
    go through update_invoice_payment_status_record; this helper exists
    only because that function always stamps real wall-clock time."""
    invoice.payment_status = PaymentStatus.paid.value
    invoice.paid_at = paid_at if paid_at is not None else datetime.now(timezone.utc)
    db.commit()
    db.refresh(invoice)


def make_quote(
    db,
    organization: Organization,
    actor: User,
    *,
    customer: Customer | None = None,
    line_items: list[QuoteLineItemCreate] | None = None,
    tax_rate: Decimal = Decimal("0"),
    expiry_date=None,
    notes: str = "",
    currency_code: CurrencyCode | None = CurrencyCode.USD,
):
    line_items = line_items or [
        QuoteLineItemCreate(description="Line 1", quantity=Decimal("1"), unit_price=Decimal("100.00"))
    ]
    return create_quote_record(
        db,
        organization.id,
        actor,
        customer,
        currency_code,
        line_items,
        tax_rate,
        expiry_date=expiry_date,
        notes=notes,
    )


def make_invitation(
    db,
    organization: Organization,
    actor: OrganizationMember,
    *,
    email: str = "invitee@example.com",
    role: InvitationRole = InvitationRole.member,
) -> tuple[OrganizationInvitation, str]:
    return invite_member_record(db, organization.id, email, role, actor)
