"""Tiered duplicate-customer detection (Phase UX5).

Four independent confidence levels, each behaving differently -- see
docs/customer_duplicate_detection.md for the full rationale:

  Level 1  tax_id   HIGH CONFIDENCE  -> blocking (enforced here AND
                                         server-side in
                                         app.services.customers, never
                                         trusting the client alone)
  Level 2  email    medium           -> warning
  Level 3  phone    medium           -> warning
  Level 4  name     low              -> suggestion, never blocks

check_customer_duplicates() issues exactly one bounded query per call
(WHERE organization_id = ..., optionally excluding the customer being
edited) -- the same shape as app.imports.customers.fetch_existing_keys,
never a query per candidate row. Comparison happens in Python against the
shared normalizers in app.customer_validation, since normalization strips
formatting the database can't compare on without a functional index (not
introduced in this phase -- see the docs file for why, and for the future
optimization path if per-organization customer counts ever outgrow this).

Never compares across organizations: every query here is scoped to a
single organization_id, so nothing in this module can leak another
tenant's customer.
"""

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_validation import (
    normalize_customer_email,
    normalize_customer_name,
    normalize_customer_phone,
    normalize_tax_id,
)
from app.models import Customer

REASON_TAX_ID = "tax_id"
REASON_EMAIL = "email"
REASON_PHONE = "phone"
REASON_NAME = "name"


class DuplicateSeverity(str, Enum):
    none = "none"
    suggestion = "suggestion"
    warning = "warning"
    blocking = "blocking"


# Highest-confidence reason wins when picking a single match's own
# severity; the overall check result's severity is the max across every
# match found (see check_customer_duplicates).
_SEVERITY_BY_REASON: dict[str, DuplicateSeverity] = {
    REASON_TAX_ID: DuplicateSeverity.blocking,
    REASON_EMAIL: DuplicateSeverity.warning,
    REASON_PHONE: DuplicateSeverity.warning,
    REASON_NAME: DuplicateSeverity.suggestion,
}
_SEVERITY_RANK: dict[DuplicateSeverity, int] = {
    DuplicateSeverity.none: 0,
    DuplicateSeverity.suggestion: 1,
    DuplicateSeverity.warning: 2,
    DuplicateSeverity.blocking: 3,
}


@dataclass
class DuplicateMatch:
    customer_id: str
    customer_name: str
    email: str
    phone: str
    tax_id: str
    reasons: list[str] = field(default_factory=list)

    @property
    def severity(self) -> DuplicateSeverity:
        return max((_SEVERITY_BY_REASON[r] for r in self.reasons), key=_SEVERITY_RANK.__getitem__)


@dataclass
class DuplicateCheckResult:
    severity: DuplicateSeverity
    matches: list[DuplicateMatch] = field(default_factory=list)


def check_customer_duplicates(
    db: Session,
    organization_id: str,
    *,
    name: str = "",
    email: str = "",
    phone: str = "",
    tax_id: str = "",
    exclude_customer_id: str | None = None,
) -> DuplicateCheckResult:
    """Checks name/email/phone/tax_id against every other customer already
    in this organization.

    An empty string for a given field means "don't check this field" --
    used by the edit flow to skip fields the user didn't actually change
    (see frontend CustomerForm.tsx: unchanged fields are sent blank so a
    pre-existing collision the user isn't touching never re-surfaces a
    warning).
    """
    norm_name = normalize_customer_name(name) if name else ""
    norm_email = normalize_customer_email(email) if email else ""
    norm_phone = normalize_customer_phone(phone) if phone else ""
    norm_tax_id = normalize_tax_id(tax_id) if tax_id else ""

    if not (norm_name or norm_email or norm_phone or norm_tax_id):
        return DuplicateCheckResult(severity=DuplicateSeverity.none, matches=[])

    query = select(
        Customer.id, Customer.name, Customer.email, Customer.phone, Customer.tax_id
    ).where(Customer.organization_id == organization_id)
    if exclude_customer_id:
        query = query.where(Customer.id != exclude_customer_id)

    matches: list[DuplicateMatch] = []
    for row_id, row_name, row_email, row_phone, row_tax_id in db.execute(query).all():
        reasons: list[str] = []
        if norm_tax_id and row_tax_id and normalize_tax_id(row_tax_id) == norm_tax_id:
            reasons.append(REASON_TAX_ID)
        if norm_email and row_email and normalize_customer_email(row_email) == norm_email:
            reasons.append(REASON_EMAIL)
        if norm_phone and row_phone and normalize_customer_phone(row_phone) == norm_phone:
            reasons.append(REASON_PHONE)
        if norm_name and row_name and normalize_customer_name(row_name) == norm_name:
            reasons.append(REASON_NAME)
        if reasons:
            matches.append(
                DuplicateMatch(
                    customer_id=row_id,
                    customer_name=row_name,
                    email=row_email,
                    phone=row_phone,
                    tax_id=row_tax_id,
                    reasons=reasons,
                )
            )

    if not matches:
        return DuplicateCheckResult(severity=DuplicateSeverity.none, matches=[])

    overall_severity = max((m.severity for m in matches), key=_SEVERITY_RANK.__getitem__)
    return DuplicateCheckResult(severity=overall_severity, matches=matches)


def find_tax_id_duplicate(
    db: Session,
    organization_id: str,
    tax_id: str,
    exclude_customer_id: str | None = None,
) -> Customer | None:
    """Server-side, defense-in-depth tax-id check used directly by
    create_customer_record/update_customer_record (app.services.customers)
    -- tax_id is the one HIGH-CONFIDENCE level this feature actually
    blocks on, so it must be enforced at the point of persistence too, not
    only advisory via check_customer_duplicates above (never trust that
    the client called POST .../check-duplicates first -- see e.g. how
    every /admin/* endpoint independently re-checks
    require_platform_permission regardless of frontend gating, same
    principle here).

    Returns the colliding Customer row, or None. Issues no query at all
    when tax_id is blank -- most customers don't have one, and this runs
    on every create/update.
    """
    norm_tax_id = normalize_tax_id(tax_id) if tax_id else ""
    if not norm_tax_id:
        return None

    query = select(Customer).where(
        Customer.organization_id == organization_id,
        Customer.tax_id != "",
    )
    if exclude_customer_id:
        query = query.where(Customer.id != exclude_customer_id)

    for candidate in db.scalars(query).all():
        if normalize_tax_id(candidate.tax_id) == norm_tax_id:
            return candidate
    return None
