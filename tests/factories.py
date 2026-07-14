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
from decimal import Decimal

from app.membership_role import InvitationRole, MembershipRole
from app.models import (
    Customer,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Product,
    User,
)
from app.schemas import CurrencyCode, InvoiceLineItemCreate, QuoteLineItemCreate
from app.security import create_access_token, hash_password
from app.services.invoices import create_invoice_record
from app.services.quotes import create_quote_record
from app.services.team import invite_member_record


def make_user(db, *, email: str = "user@example.com", verified: bool = True) -> User:
    from datetime import datetime, timezone

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
    organization = Organization(name=name)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


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
) -> Customer:
    customer = Customer(organization_id=organization.id, name=name, email=email)
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
