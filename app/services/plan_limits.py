"""Phase 14C -- the single centralized place that enforces plan limits.

Reuses Phase 14A's entitlement service (the only reader of Plan columns)
and Phase 14B's usage service (the only place that counts a resource) --
this module adds nothing but the comparison between the two, plus the
one atomic mechanism that makes that comparison race-safe. No router or
service anywhere else may compare `used >= limit` itself; every creation
path calls check_limit() (or, for bulk imports, remaining_capacity())
here instead.

Storage is deliberately absent from the dispatch table below: this app
has no file-storage subsystem at all (see app.services.organization_usage
.count_storage's own docstring), so there is nothing to enforce yet.
Calling check_limit() for storage hits the same "unknown resource" path
as a genuine typo -- fails closed, on purpose, rather than silently
allowing or fabricating a check against nothing.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization
from app.services.entitlements import Entitlements, PlanLimit, get_limit, get_organization_entitlements
from app.services.organization_usage import (
    count_ai_actions_current_month,
    count_customers,
    count_invoices_current_month,
    count_products,
    count_quotes_current_month,
    count_users,
)


class LimitedResource(str, Enum):
    """Wire/API-facing resource names -- deliberately match
    app.services.organization_usage.UsageSnapshot's own field names
    ("users", not "max_users") since these are what the frontend already
    renders on the Plan & Limits page and what the 409 error contract's
    "resource" field reports."""

    users = "users"
    customers = "customers"
    products = "products"
    invoices = "invoices"
    quotes = "quotes"
    ai_actions = "ai_actions"


@dataclass(frozen=True)
class _ResourceSpec:
    plan_limit: PlanLimit
    count_fn: Callable[[Session, str], int]


_RESOURCE_SPECS: dict[LimitedResource, _ResourceSpec] = {
    LimitedResource.users: _ResourceSpec(PlanLimit.max_users, count_users),
    LimitedResource.customers: _ResourceSpec(PlanLimit.max_customers, count_customers),
    LimitedResource.products: _ResourceSpec(PlanLimit.max_products, count_products),
    LimitedResource.invoices: _ResourceSpec(PlanLimit.max_invoices_per_month, count_invoices_current_month),
    LimitedResource.quotes: _ResourceSpec(PlanLimit.max_quotes_per_month, count_quotes_current_month),
    LimitedResource.ai_actions: _ResourceSpec(PlanLimit.max_ai_actions_per_month, count_ai_actions_current_month),
    # storage intentionally omitted -- see module docstring.
}


class UnknownLimitedResourceError(Exception):
    """Raised when check_limit()/remaining_capacity() is called with a
    resource this module has no dispatch entry for (storage, or a typo/
    a new resource added to LimitedResource without updating
    _RESOURCE_SPECS). Fails closed: never silently treated as unlimited
    or as already-allowed."""


class PlanLimitExceededError(Exception):
    """Carries every field the 409 plan_limit_reached response needs
    (see app.schemas.PlanLimitReachedDetail) -- routers never rebuild
    this from scratch, they just serialize it."""

    def __init__(
        self,
        *,
        resource: LimitedResource,
        used: int,
        limit: int,
        plan_id: str,
        plan_code: str,
        plan_name: str,
    ) -> None:
        super().__init__(
            f"Plan limit reached for {resource.value}: used={used} limit={limit} plan={plan_code}"
        )
        self.resource = resource
        self.used = used
        self.limit = limit
        self.plan_id = plan_id
        self.plan_code = plan_code
        self.plan_name = plan_name

    def to_error_detail(self) -> dict:
        """The exact 409 body shape every router returns for this error --
        one place builds it so no router hand-assembles this dict
        itself (matching this codebase's existing convention of plain
        dict `detail=` payloads for structured 409s, e.g.
        plan_version_conflict). The frontend must never parse `message`;
        every field it needs is structured."""
        return {
            "code": "plan_limit_reached",
            "resource": self.resource.value,
            "used": self.used,
            "limit": self.limit,
            "plan": {"id": self.plan_id, "code": self.plan_code, "name": self.plan_name},
            "message": (
                f"You've reached your plan's {self.resource.value.replace('_', ' ')} limit "
                f"({self.used}/{self.limit}) on the {self.plan_name} plan."
            ),
        }


def _lock_organization(db: Session, organization_id: str) -> None:
    """Takes a row-level lock on this one organization's own row for the
    remainder of the current transaction -- serializes concurrent
    creation requests for THIS organization only (never a table lock,
    never another organization) so that "count usage, compare to limit,
    insert the new row" can't race between two concurrent requests each
    seeing a stale, pre-insert count. Verified to be silently accepted
    (a harmless no-op) on SQLite, which has no row-locking syntax of its
    own and already serializes writers at a coarser level; genuinely
    enforced on Postgres (production). Must be called, and the resulting
    row's insert/commit must happen, within the same db session/
    transaction -- callers that check the limit in one transaction and
    insert in another get no protection from this at all."""
    db.execute(select(Organization.id).where(Organization.id == organization_id).with_for_update())


def _resolve(resource: LimitedResource) -> _ResourceSpec:
    spec = _RESOURCE_SPECS.get(resource)
    if spec is None:
        raise UnknownLimitedResourceError(f"No plan-limit enforcement is defined for resource {resource!r}")
    return spec


def remaining_capacity(db: Session, organization_id: str, resource: LimitedResource) -> int | None:
    """Returns None for unlimited, otherwise how many more of `resource`
    this organization may create right now (never negative). Locks the
    organization row first, for the same reason check_limit() does --
    the caller (a bulk import) is expected to hold that lock for the
    remainder of its own single transaction while it persists rows one
    at a time, decrementing its own local counter rather than re-calling
    this per row."""
    spec = _resolve(resource)
    _lock_organization(db, organization_id)
    entitlements: Entitlements = get_organization_entitlements(db, organization_id)
    limit = get_limit(entitlements, spec.plan_limit)
    if limit is None:
        return None
    used = spec.count_fn(db, organization_id)
    return max(0, limit - used)


def check_limit(
    db: Session,
    organization_id: str,
    resource: LimitedResource,
    *,
    additional: int = 1,
) -> None:
    """Raises PlanLimitExceededError if creating `additional` more of
    `resource` (default 1, the ordinary single-item-creation case) would
    put this organization's usage over its plan's limit. A no-op
    (returns None) when the limit is unlimited or usage stays within it.
    Locks the organization row first -- see _lock_organization -- so the
    count this reads can't go stale before the caller's own insert
    commits in the same transaction."""
    spec = _resolve(resource)
    _lock_organization(db, organization_id)
    entitlements: Entitlements = get_organization_entitlements(db, organization_id)
    limit = get_limit(entitlements, spec.plan_limit)
    if limit is None:
        return
    used = spec.count_fn(db, organization_id)
    if used + additional > limit:
        raise PlanLimitExceededError(
            resource=resource,
            used=used,
            limit=limit,
            plan_id=entitlements.plan_id,
            plan_code=entitlements.plan_code,
            plan_name=entitlements.plan_name,
        )
