"""Phase 14C -- the single centralized place that enforces plan limits.

Phase 17B: every limit/used number here is sourced from
app.billing.capabilities (get_organization_capabilities + its
remaining_* functions), never recomputed independently -- this module
adds nothing but the row lock and the atomic check-and-raise ceremony on
top of numbers capabilities.py already computes correctly. Before this
phase, this module called app.services.entitlements/organization_usage
directly, which meant the exact same "how many of X can this org still
create" computation existed twice (once here, once in capabilities.py);
routing it all through capabilities.py's OrganizationCapabilities
removes that duplication while leaving every existing caller's contract
(check_limit()'s signature, PlanLimitExceededError's shape, the 409
response body) completely unchanged. No router or service anywhere else
may compare `used >= limit` itself; every creation path calls
check_limit() (or, for bulk imports, remaining_capacity()) here instead.

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

from app.billing.capabilities import (
    OrganizationCapabilities,
    get_organization_capabilities,
    remaining_ai_actions_quota,
    remaining_api_keys,
    remaining_customers,
    remaining_invoice_quota,
    remaining_products,
    remaining_quote_quota,
    remaining_users,
    remaining_webhooks,
)
from app.models import Organization


class LimitedResource(str, Enum):
    """Wire/API-facing resource names -- deliberately match
    app.services.organization_usage.UsageSnapshot's own field names
    ("users", not "max_users") since these are what the frontend already
    renders on the Plan & Limits page and what the 409 error contract's
    "resource" field reports. `api_keys`/`webhooks` are Phase 17B
    additions -- Phase 17A's capabilities.py already exposed their
    remaining_* numbers, this is the first phase to actually enforce
    them at creation time."""

    users = "users"
    customers = "customers"
    products = "products"
    invoices = "invoices"
    quotes = "quotes"
    ai_actions = "ai_actions"
    api_keys = "api_keys"
    webhooks = "webhooks"


@dataclass(frozen=True)
class _ResourceSpec:
    limit_fn: Callable[[OrganizationCapabilities], int | None]
    used_fn: Callable[[OrganizationCapabilities], int]
    remaining_fn: Callable[[OrganizationCapabilities], int | None]


_RESOURCE_SPECS: dict[LimitedResource, _ResourceSpec] = {
    LimitedResource.users: _ResourceSpec(
        lambda c: c.entitlements.max_users, lambda c: c.usage_users, remaining_users
    ),
    LimitedResource.customers: _ResourceSpec(
        lambda c: c.entitlements.max_customers, lambda c: c.usage_customers, remaining_customers
    ),
    LimitedResource.products: _ResourceSpec(
        lambda c: c.entitlements.max_products, lambda c: c.usage_products, remaining_products
    ),
    LimitedResource.invoices: _ResourceSpec(
        lambda c: c.entitlements.max_invoices_per_month, lambda c: c.usage_invoices, remaining_invoice_quota
    ),
    LimitedResource.quotes: _ResourceSpec(
        lambda c: c.entitlements.max_quotes_per_month, lambda c: c.usage_quotes, remaining_quote_quota
    ),
    LimitedResource.ai_actions: _ResourceSpec(
        lambda c: c.entitlements.max_ai_actions_per_month,
        lambda c: c.usage_ai_actions,
        remaining_ai_actions_quota,
    ),
    LimitedResource.api_keys: _ResourceSpec(
        lambda c: c.entitlements.max_api_keys, lambda c: c.usage_api_keys, remaining_api_keys
    ),
    LimitedResource.webhooks: _ResourceSpec(
        lambda c: c.entitlements.max_webhooks, lambda c: c.usage_webhooks, remaining_webhooks
    ),
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
    caps = get_organization_capabilities(db, organization_id)
    return spec.remaining_fn(caps)


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
    commits in the same transaction.

    For creating ONE row at a time from a single request, this is the
    right call. A caller creating MANY rows in one transaction (a bulk
    CSV import) should use open_limit_tracker() instead -- see that
    function's own docstring for why calling check_limit() per row
    re-resolves the same entitlements+usage numbers (1 entitlements
    query + 8 usage-count queries, see
    app.billing.capabilities.get_organization_capabilities) on every
    single row for no reason, when nothing about the organization's plan
    or its usage-outside-this-import changes mid-loop."""
    spec = _resolve(resource)
    _lock_organization(db, organization_id)
    caps = get_organization_capabilities(db, organization_id)
    limit = spec.limit_fn(caps)
    if limit is None:
        return
    used = spec.used_fn(caps)
    if used + additional > limit:
        raise PlanLimitExceededError(
            resource=resource,
            used=used,
            limit=limit,
            plan_id=caps.entitlements.plan_id,
            plan_code=caps.entitlements.plan_code,
            plan_name=caps.entitlements.plan_name,
        )


@dataclass
class LimitTracker:
    """Returned by open_limit_tracker() -- holds one resource's limit and
    plan info resolved ONCE, plus a running `used` count this tracker
    itself advances locally. `.consume()` is the per-row replacement for
    calling check_limit() again: a pure, in-memory comparison, no query.
    """

    resource: LimitedResource
    limit: int | None
    used: int
    plan_id: str
    plan_code: str
    plan_name: str

    def consume(self, additional: int = 1) -> None:
        """Raises PlanLimitExceededError with the exact same shape
        check_limit() would raise -- callers (app.imports.*) that
        already catch PlanLimitExceededError per row need no changes at
        all beyond swapping which function raises it. Deliberately keeps
        raising on every call once the cap is reached (never "raise
        once, then silently stop counting"), matching check_limit()'s
        own per-row behavior when called repeatedly past the limit --
        every row past the cap must still be reported by
        app.imports.base.build_confirm as plan_limit_reached, not just
        the first one."""
        if self.limit is not None and self.used + additional > self.limit:
            raise PlanLimitExceededError(
                resource=self.resource,
                used=self.used,
                limit=self.limit,
                plan_id=self.plan_id,
                plan_code=self.plan_code,
                plan_name=self.plan_name,
            )
        self.used += additional


def open_limit_tracker(db: Session, organization_id: str, resource: LimitedResource) -> LimitTracker:
    """The bulk-creation counterpart to check_limit() -- resolves this
    organization's limit/used/plan info for `resource` exactly ONCE
    (locking the organization row exactly once, see _lock_organization),
    for a caller (a CSV import's persist function, built once per import
    and then invoked once per row -- see app.imports.customers/products
    .make_persist_fn) that will go on to create many rows within the
    SAME transaction. Every subsequent row calls the returned tracker's
    own .consume() instead of check_limit(), which does zero additional
    queries.

    Must be called, and every .consume() call plus its corresponding
    row insert, within the same db session/transaction as each other --
    same requirement _lock_organization's own docstring already states
    for check_limit(), unchanged here."""
    spec = _resolve(resource)
    _lock_organization(db, organization_id)
    caps = get_organization_capabilities(db, organization_id)
    return LimitTracker(
        resource=resource,
        limit=spec.limit_fn(caps),
        used=spec.used_fn(caps),
        plan_id=caps.entitlements.plan_id,
        plan_code=caps.entitlements.plan_code,
        plan_name=caps.entitlements.plan_name,
    )
