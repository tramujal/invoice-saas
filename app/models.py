import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.assistant_action_status import AssistantActionStatus
from app.database import engine
from app.job_status import JobStatus
from app.membership_role import MembershipRole
from app.membership_status import MembershipStatus
from app.organization_status import OrganizationStatus
from app.payment_status import PaymentStatus
from app.product_type import ProductType
from app.quote_status import QuoteStatus
from app.reminder_status import ReminderStatus
from app.reminder_type import ReminderType
from app.billing_period import BillingPeriod
from app.subscription_event_type import SubscriptionEventType
from app.subscription_status import SubscriptionStatus
from app.user_status import UserStatus
from app.whatsapp_identity_status import WhatsAppIdentityStatus
from app.schema_migrations import run_startup_migrations


class Base(DeclarativeBase):
    pass


# Fixed codes for the four built-in plans seeded by
# _seed_default_plans (see app.schema_migrations) -- referenced here, not
# just in the migration, so app.services.entitlements and registration
# (app.routers.auth.register) never have to hardcode the string again.
PLAN_CODE_FREE = "free"
PLAN_CODE_STARTER = "starter"
PLAN_CODE_PRO = "pro"
PLAN_CODE_ENTERPRISE = "enterprise"

# Fixed, non-random primary keys for the four seeded plan rows -- same
# rationale as PLATFORM_SETTINGS_SINGLETON_ID: a literal, known-ahead-of-
# time id is what lets the idempotent migration that adds
# Organization.plan_id use a plain SQL-level DEFAULT (see
# _add_organization_plan_id) instead of needing a data migration step to
# backfill a randomly-generated UUID it couldn't have known in advance.
PLAN_ID_FREE = "plan_free"
PLAN_ID_STARTER = "plan_starter"
PLAN_ID_PRO = "plan_pro"
PLAN_ID_ENTERPRISE = "plan_enterprise"


class Plan(Base):
    """A commercial plan definition -- what an organization is entitled
    to, never what it has actually used (usage tracking/enforcement is
    explicitly out of scope for this phase; see app.services.entitlements
    for the one place that reads these columns).

    `code` is immutable forever once created (enforced at the API layer,
    app.routers.platform_admin -- PATCH never accepts it) since it's the
    stable identifier registration and any future billing integration
    would key off of, unlike `name`/`description` which are just display
    text. Plans are never deleted, only deactivated (`is_active=False`);
    an inactive plan can still be read (an org already on it keeps its
    entitlements) but can never be newly assigned -- see
    app.routers.platform_admin.update_organization_plan.

    Exactly one row must have `is_default=True` at all times -- enforced
    transactionally by POST .../make-default (clears the old default and
    sets the new one in the same UPDATE-guarded transaction), never by a
    database constraint alone, since flipping a boolean on two rows
    safely needs a transaction regardless.

    Every *_per_month / max_* limit and storage_limit_mb follow one rule,
    documented once here rather than on each column: NULL means
    unlimited, 0 means unavailable, and a positive integer is a hard
    limit. The *_enabled feature booleans are commercial entitlements
    only -- whether the plan is SUPPOSED to allow the capability, not
    whether it's actually wired up and enforced anywhere yet (this phase
    defines entitlements; enforcement is a later phase).

    `version` is the same optimistic-concurrency token PlatformSettings
    already uses (see app.routers.platform_admin.update_platform_settings
    for the exact pattern) -- PATCH/activate/deactivate/make-default all
    go through one atomic `UPDATE ... WHERE version = expected_version`,
    never ORM attribute mutation followed by a blind commit.

    Phase 17A adds pricing (`monthly_price`/`yearly_price`/`currency`),
    `public` (whether to surface this plan to prospective customers vs.
    a legacy plan kept only for its existing subscribers), and 4 more
    commercial feature flags plus 2 more limits -- extending this same
    row rather than introducing a second "billing plan" concept, since
    `code`/`name`/`sort_order`/`is_active` already fill the "immutable
    internal identifier / editable display name / display order / active"
    roles Phase 17A's spec describes (see that phase's own completion
    report for this exact mapping). `code` remains the one thing that
    never changes once a plan is created -- see the module-level note on
    PlanUpdateRequest.

    `monthly_price`/`yearly_price` are NULL to mean "custom/contact us"
    (the Enterprise seed row), the same NULL-means-unbounded convention
    every limit column on this model already uses -- never a magic
    sentinel number like -1 or 0 (0 is a valid free price).
    """

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_customers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_products: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_invoices_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_quotes_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_ai_actions_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_limit_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Phase 17A additions -- same NULL=unlimited/0=unavailable convention.
    max_api_keys: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_webhooks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    custom_branding_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_access_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    advanced_reports_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase 17A additions -- commercial entitlements only, same rule as
    # the three flags above (whether the plan is SUPPOSED to allow the
    # capability; enforcement is a future phase, see
    # app.billing.capabilities for the read-only capability layer this
    # phase actually builds).
    analytics_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    forecasting_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    ai_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    background_jobs_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Phase 23 additions -- the experimental WhatsApp assistant. Same
    # NULL=unlimited/0=unavailable convention as every other limit column
    # above, and the same "commercial entitlement only, not itself
    # enforcement" rule as every other *_enabled flag. whatsapp_enabled
    # gates the feature as a whole (checked via app.billing.enforcement
    # .require_whatsapp before ANY inbound message is processed);
    # voice_messages_enabled is a separate, narrower flag so a plan can
    # allow text commands without allowing (costlier, transcription-
    # dependent) voice notes. max_whatsapp_users caps how many
    # WhatsAppIdentity rows may be `verified` at once per organization;
    # monthly_whatsapp_actions is a distinct quota from
    # max_ai_actions_per_month -- see app.services.organization_usage
    # .count_whatsapp_actions_current_month for why this counts every
    # processed inbound WhatsApp message (read-only queries included),
    # not just the subset that also creates an AssistantAction.
    whatsapp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    voice_messages_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    max_whatsapp_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_whatsapp_actions: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 17A pricing -- informational only. No checkout, no charging,
    # no provider anywhere reads these yet; they exist so a future
    # payment-provider integration has real numbers to point at instead
    # of a second migration. NULL means "contact us" / custom pricing.
    monthly_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    yearly_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD", server_default="USD")
    public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organizations: Mapped[list["Organization"]] = relationship(back_populates="plan")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="plan")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    next_invoice_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )
    currency_code: Mapped[str] = mapped_column(
        String(8), nullable=False, default="USD", server_default="USD"
    )
    tax_label: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Tax ID", server_default="Tax ID"
    )
    # IANA timezone identifier (e.g. "America/Montevideo") -- every due-date
    # comparison in the app uses this, via app.org_time.get_organization_today,
    # rather than the server's UTC date. Defaults to UTC, the only default
    # that makes no assumption about where a business actually is.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    # Automatic payment reminders default OFF for every organization,
    # including new ones -- automatically emailing a business's customers is
    # exactly the kind of thing that should never turn on silently; see
    # app/jobs/send_due_invoice_reminders.py.
    reminders_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Comma-separated day-offset lists (e.g. "7,3,1") -- see
    # app/reminder_settings.py for why this is a validated string rather
    # than a native array column (SQLite has no portable array type).
    reminder_before_due_days: Mapped[str] = mapped_column(
        String(64), nullable=False, default="3", server_default="3"
    )
    reminder_on_due_date: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    reminder_after_due_days: Mapped[str] = mapped_column(
        String(64), nullable=False, default="7", server_default="7"
    )
    next_quote_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Independent of reminders_enabled above -- a business may want
    # automatic payment reminders without automatic expiring-quote
    # reminders, or vice versa. Off by default for every organization,
    # same "never opt a business into outbound email silently" rationale
    # as reminders_enabled -- see app/jobs/send_expiring_quote_reminders.py.
    quote_reminders_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Comma-separated day-offset list (e.g. "3") -- same portable-string
    # convention as reminder_before_due_days; see app/reminder_settings.py.
    quote_reminder_before_expiry_days: Mapped[str] = mapped_column(
        String(64), nullable=False, default="3", server_default="3"
    )
    # Platform-administration axis (see app.organization_status) -- set only
    # via POST /admin/organizations/{id}/suspend|reactivate
    # (platform.organizations.manage). Never a soft-delete: memberships,
    # invoices, quotes, and customers are untouched by a status change.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=OrganizationStatus.active.value,
        server_default=OrganizationStatus.active.value,
    )
    # ON DELETE RESTRICT (not CASCADE/SET NULL): a plan being referenced
    # by any organization must never simply vanish out from under it --
    # see Plan's own docstring on why plans are deactivated, never
    # deleted, which is what makes RESTRICT here safe in practice (there
    # is no code path that ever attempts to delete a Plan row at all).
    #
    # Deprecated as of Phase 17A: no code path reads this column anymore
    # (app.services.entitlements resolves entitlements via the
    # organization's Subscription -> Plan instead -- see Subscription's
    # own docstring below). Left in place, still written at registration
    # as a harmless denormalized copy, rather than dropped now: dropping
    # an ON DELETE RESTRICT-referenced column is a separately-riskier
    # migration with no behavioral benefit this phase. A future cleanup
    # phase can remove it once Subscription has been the sole source of
    # truth in production for a while.
    plan_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("plans.id", ondelete="RESTRICT"),
        nullable=False,
        server_default=PLAN_ID_FREE,
    )

    members: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organization"
    )
    customers: Mapped[list["Customer"]] = relationship(back_populates="organization")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="organization")
    products: Mapped[list["Product"]] = relationship(back_populates="organization")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="organization")
    plan: Mapped["Plan"] = relationship(back_populates="organizations")
    subscription: Mapped["Subscription | None"] = relationship(
        back_populates="organization", uselist=False, passive_deletes=True
    )


class Subscription(Base):
    """The single source of truth for what an organization is entitled
    to -- see app.services.entitlements.get_organization_plan, which
    resolves through this table's own `plan_id`, never through
    Organization.plan_id (deprecated, see that column's own comment).
    Every organization owns exactly one Subscription row, enforced by the
    unique constraint on `organization_id` below, from the moment it's
    created at registration (see app.billing.service.BillingService
    .create_subscription, called from app.routers.auth.register) onward.

    `provider_name`/`provider_reference` are nullable -- NULL for every
    subscription with no attached payment provider (still every
    subscription as of Phase 17A), populated once by
    app.billing.service.BillingService.attach_provider_subscription when
    a checkout_completed webhook event arrives from Phase 18's provider
    layer (app.billing.provider_base.BillingProvider). This model itself
    still has zero awareness of which provider, if any, is attached --
    `provider_name` is just the provider's own short identifier string
    (e.g. "stripe"), read back out only to route an incoming webhook to
    the right BillingProvider implementation.

    `status` supports `past_due`/`paused` for the same provider-driven
    reason (see app.subscription_status.SubscriptionStatus) -- `past_due`
    is set by BillingService.mark_past_due on a provider's payment_failed
    webhook event; `paused` still has no writer anywhere in this app.

    `metadata_json` is a nullable, JSON-encoded TEXT column (never a
    native JSON column type) -- the same portable-across-SQLite/Postgres
    convention app.models.BackgroundJob.payload and
    app.models.PlatformAuditLog.details already use. Reserved for
    forward-compatible, non-critical annotations; app.billing.service
    never depends on anything stored here to make a decision.

    `version` provides the same optimistic-concurrency guarantee as
    Plan/PlatformSettings's `expected_version` pattern, but through a
    different mechanism: those two are updated by routers issuing a
    hand-written `UPDATE ... WHERE id = :id AND version = :expected_version`
    directly. Subscription is instead always mutated through
    app.billing.service.BillingService, which only ever assigns ORM
    attributes and calls db.commit() -- so this column is wired up via
    SQLAlchemy's own `version_id_col` mapper feature (see
    `__mapper_args__` below) instead of a hand-written conditional
    UPDATE. Every flush SQLAlchemy performs for this class already
    scopes its UPDATE to `WHERE version = <the value this row was loaded
    with>` and auto-increments it on success; if a concurrent writer
    already advanced the row first, the flush affects zero rows and
    SQLAlchemy raises `sqlalchemy.orm.exc.StaleDataError`, which
    BillingService._commit translates into the domain-level
    `app.billing.service.SubscriptionConflictError` (never a silent
    lost update) -- see that class's own docstring for the full
    request/webhook race this protects against.
    """

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SubscriptionStatus.active.value
    )
    billing_period: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BillingPeriod.monthly.value
    )
    trial_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL until a checkout completes with a provider attached -- see class docstring.
    provider_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # See `version`'s own docstring above -- this is what turns every
    # BillingService flush into an automatic `WHERE version = ...`
    # conditional UPDATE, the same guarantee Plan/PlatformSettings get
    # from a hand-written statement instead.
    __mapper_args__ = {"version_id_col": version}

    organization: Mapped["Organization"] = relationship(back_populates="subscription")
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")
    events: Mapped[list["SubscriptionEvent"]] = relationship(
        back_populates="subscription", order_by="SubscriptionEvent.created_at", passive_deletes=True
    )


class SubscriptionEvent(Base):
    """Subscription HISTORY -- not the platform Audit Log
    (PlatformAuditLog, which is untouched by this phase and keeps
    recording platform-admin actions exactly as before). This table
    answers "what happened to this subscription over time," written by
    app.billing.service.BillingService itself on every mutating call,
    including system-triggered transitions (trial_expired,
    subscription_expired) that have no human actor -- `actor_user_id` is
    nullable for exactly that case, the same nullable-actor precedent
    PlatformAuditLog.actor_user_id already sets (there: SET NULL after a
    user is deleted; here: NULL from the moment of creation for a
    system-triggered event).

    `previous_values`/`new_values`/`metadata_json` are nullable, JSON-
    encoded TEXT columns -- same portable-JSON-as-TEXT convention as
    Subscription.metadata_json above. Append-only: no route ever updates
    or deletes a row here.
    """

    __tablename__ = "subscription_events"
    __table_args__ = (
        Index("ix_subscription_events_subscription_id", "subscription_id"),
        Index("ix_subscription_events_organization_id", "organization_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_values: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    subscription: Mapped["Subscription"] = relationship(back_populates="events")


class ProviderWebhookReceipt(Base):
    """Idempotency record for one incoming payment-provider webhook event
    -- new infrastructure introduced by Phase 18's provider layer
    (app.billing.provider_base), NOT a change to Subscription/Plan/
    SubscriptionEvent (Phase 17A/17B's frozen billing foundations).
    Every provider's webhook contract is built around the possibility of
    the same event being delivered more than once (a slow/failed
    acknowledgment, a manual redelivery from the provider's own
    dashboard); app.routers.billing_webhooks writes exactly one row here
    per event_id BEFORE calling
    app.billing.service.BillingService.sync_from_webhook_event, and skips
    processing entirely (returning 200 without re-applying any mutation)
    if a row for that `(provider_name, event_id)` pair already exists.

    Deliberately its own table rather than a column/index trick on
    SubscriptionEvent -- an event can be legitimately received and
    rejected (bad signature, unknown provider_reference) before any
    SubscriptionEvent would ever be written for it, so idempotency can't
    depend on one existing.
    """

    __tablename__ = "provider_webhook_receipts"
    __table_args__ = (UniqueConstraint("provider_name", "event_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderCustomer(Base):
    """Caches the provider-side customer id for one organization on one
    provider -- Phase 18.1 hardening, so
    app.billing.service.BillingService.start_checkout creates a Stripe (or
    future Mercado Pago/Paddle/LemonSqueezy) customer record AT MOST ONCE
    per organization per provider, reusing `provider_customer_id` on every
    later checkout instead of accumulating a fresh, orphaned customer
    record on the provider's side every time.

    Not to be confused with app.billing.provider_base.ProviderCustomer,
    the small immutable dataclass a BillingProvider.create_customer() call
    returns in memory -- that value object is never persisted directly;
    this ORM row is what makes its `id` durable and reusable across
    requests. Distinct names, distinct modules, distinct purpose: this
    table is a cache keyed by (organization_id, provider_name); that
    dataclass is a single call's return value.

    `provider_name` (not a foreign key -- just the provider's own short
    string identifier, e.g. "stripe") lets the same organization hold one
    cached customer per provider it has ever used, consistent with
    Subscription.provider_name's own convention. The unique constraint is
    what makes concurrent checkout attempts for the same organization
    safe: a race that gets past the application-level existence check
    still can't insert two rows -- see BillingService
    ._get_or_create_provider_customer's own docstring for how the losing
    request recovers.
    """

    __tablename__ = "provider_customers"
    __table_args__ = (UniqueConstraint("organization_id", "provider_name"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Null until the user completes /auth/verify-email. Deliberately a
    # nullable timestamp rather than a bool: it doubles as a record of *when*
    # verification happened, at no extra cost. Existing users (created
    # before this feature existed) are backfilled to a non-null value by the
    # migration — see _add_user_email_verified_at — so nobody already using
    # the app is retroactively locked out.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Platform-administration authorization axis -- entirely independent
    # from OrganizationMember.role (see app.platform_permissions). NULL
    # means "not a platform admin"; deliberately distinct from an empty
    # string to avoid a falsy-but-set footgun. Set only via the
    # app.scripts.grant_platform_role bootstrap CLI or a future
    # platform.roles.manage endpoint -- never through ordinary signup.
    platform_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Account-level access axis (see app.user_status) -- entirely separate
    # from platform_role above and from OrganizationMember.role. Disabling
    # blocks authentication itself (app.deps.get_current_user), before
    # either other axis is ever consulted. Deliberately no disabled_at/
    # disabled_reason columns here: app.models.PlatformAuditLog already
    # records the timestamp and reason for every disable/enable action,
    # and duplicating them on User would be two sources of truth for the
    # same fact with no way to keep them in sync.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UserStatus.active.value)

    memberships: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="user", foreign_keys="OrganizationMember.user_id"
    )

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrganizationMember(Base):
    """A user's real, established relationship to an organization --
    always represents someone who has actually joined (created the org at
    registration, or accepted an OrganizationInvitation), never a pending
    invite. This is deliberate: require_org_member's existence-check
    query, and every other membership-based authorization check in this
    app, must never be satisfiable by a not-yet-accepted invitation. See
    OrganizationInvitation for the entire pre-membership lifecycle, kept
    in its own table for exactly this reason.

    role is a single, ordinary field -- multiple members may simultaneously
    hold role="owner" (see app.permissions for the full role -> capability
    matrix). The only hard invariant, enforced in app.services.team, is
    "at least one active owner, always"; granting/revoking ownership is
    just a role change with extra guards, not a special data state.
    """

    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MembershipRole.member.value,
        server_default=MembershipRole.member.value,
    )
    # Soft-removal only -- see MembershipStatus.removed's docstring. Never
    # deleted, since Invoice/Quote.created_by_user_id and invited_by/
    # role_changed_by/removed_by on other rows may still reference this
    # membership's history.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MembershipStatus.active.value,
        server_default=MembershipStatus.active.value,
    )
    # Audit-only FKs -- never used for authorization, only for "who did
    # this" display. ON DELETE SET NULL so a deleted user can never cascade
    # into losing another member's history.
    invited_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NOT NULL -- every membership row, by construction, represents an
    # already-joined relationship (see the class docstring). For the
    # org-creating owner this equals created_at; for an invitee it's when
    # they accepted.
    #
    # accepted_at/created_at/updated_at all set a client-side `default=`
    # (not just `server_default=`) because, unlike every other table here
    # (created fresh via Base.metadata.create_all(), which faithfully
    # emits server_default into the real CREATE TABLE DDL), these three
    # columns were added to an existing table via a raw ALTER TABLE ADD
    # COLUMN in app.schema_migrations, which historically didn't attach a
    # DB-level DEFAULT -- so relying on server_default alone silently left
    # every membership row created since then with a NULL timestamp.
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    # Covers "who changed role" AND "who granted/revoked ownership" --
    # ownership is just a role change, so one field serves both audit asks.
    role_changed_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(
        back_populates="memberships", foreign_keys=[user_id]
    )
    organization: Mapped["Organization"] = relationship(back_populates="members")
    inviter: Mapped["User | None"] = relationship(foreign_keys=[invited_by])

    @property
    def user_email(self) -> str:
        return self.user.email

    @property
    def invited_by_email(self) -> str | None:
        # User has no display-name field anywhere in this app -- email is
        # already the sole user-facing identifier (see login/register),
        # so it's reused here rather than inventing a name field.
        return self.inviter.email if self.inviter is not None else None

    @property
    def permissions(self) -> list[str]:
        """The full permission set app.permissions.ROLE_PERMISSIONS grants
        this membership's current role. Exposed so API consumers (frontend
        UI gating, future integrations) key off actual capabilities rather
        than the role name itself -- role -> permission is defined in
        exactly one place (app.permissions), never re-derived here."""
        from app.permissions import ROLE_PERMISSIONS

        return sorted(p.value for p in ROLE_PERMISSIONS[MembershipRole(self.role)])


class OrganizationInvitation(Base):
    """The entire pre-membership lifecycle of an invite -- deliberately
    kept out of OrganizationMember (see that class's docstring for why: an
    invitation targets an email that may not have a User row yet, and
    OrganizationMember.user_id is NOT NULL). Never soft-deleted: cancelling
    an invitation removes the row outright (there is no history worth
    keeping for something that was never accepted), and accepting it sets
    accepted_at once, permanently, which is this table's entire single-use
    guarantee -- see app.services.team.get_invitation_by_token.

    role is intentionally the narrower InvitationRole (never "owner") --
    ownership can only ever be granted through the dedicated
    grant-ownership action once someone is already a real member.
    """

    __tablename__ = "organization_invitations"
    __table_args__ = (Index("ix_org_invitations_org_email", "organization_id", "email"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Unique, SHA-256 via app.tokens.hash_token -- mirrors
    # PasswordResetToken.token_hash exactly. "Resend" rotates this column
    # in place (new token, new expiry) rather than inserting a new row, so
    # at most one valid token per pending invitation ever exists.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship()
    inviter: Mapped["User | None"] = relationship()

    @property
    def created_by_email(self) -> str | None:
        return self.inviter.email if self.inviter is not None else None


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    address: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # Optional. No DB-level uniqueness (matching email's existing lax
    # behavior above) — duplicate detection is an application-level,
    # per-organization concern (see app/customer_validation.py's
    # normalize_tax_id and app/imports/customers.py), never a global
    # constraint that could affect other organizations.
    tax_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(back_populates="customers")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("organization_id", "invoice_number"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invoice_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=PaymentStatus.pending.value,
        server_default=PaymentStatus.pending.value,
    )
    # Permanently pinned at creation time from the organization's
    # currency/language at that moment (or an explicit override, for
    # currency). Deliberately independent of Organization.currency_code /
    # Organization.language, which are only defaults for *new* invoices —
    # changing them must never alter a previously created invoice's PDF,
    # email, or displayed currency. See app/currency.py / app/localization.py,
    # whose get_currency_code()/get_language() helpers accept an Invoice
    # here exactly as they accept an Organization elsewhere (both just need
    # a .currency_code / .language attribute).
    currency_code: Mapped[str] = mapped_column(
        String(8), nullable=False, default="USD", server_default="USD"
    )
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Nullable, never backfilled for pre-existing invoices (see
    # app/effective_status.py's fallback rule for exactly why that's safe).
    # A plain calendar date -- no time-of-day component, so comparisons
    # against "today" are never ambiguous the way a datetime would be.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Snapshot of the billed customer's own fields, taken at creation time
    # (app.services.invoices.create_invoice_record) -- mirrors
    # InvoiceLineItem's own description/unit_price snapshot exactly:
    # editing (or even deleting) the Customer row afterward must never
    # alter what a previously issued invoice displays. Nullable because
    # (a) an invoice may have no customer at all, and (b) rows created
    # before this column existed can only be best-effort backfilled from
    # the customer's CURRENT data (see app.schema_migrations
    # ._add_document_customer_snapshots) -- there is no history of a
    # customer's past field values anywhere in this app, so a pre-
    # existing invoice whose customer was edited since it was issued can
    # never be perfectly reconstructed. customer_name/customer_phone
    # below read these first, falling back to the live relationship only
    # when the snapshot itself is still null.
    customer_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_email_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customer_address_snapshot: Mapped[str | None] = mapped_column(String(512), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="invoices")
    customer: Mapped["Customer | None"] = relationship(back_populates="invoices")
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["InvoiceReminder"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    @property
    def customer_name(self) -> str | None:
        if self.customer_name_snapshot is not None:
            return self.customer_name_snapshot
        return self.customer.name if self.customer is not None else None

    @property
    def customer_phone(self) -> str | None:
        if self.customer_phone_snapshot is not None:
            return self.customer_phone_snapshot
        return self.customer.phone if self.customer is not None else None

    @property
    def effective_payment_status(self) -> "PaymentStatus":
        """The single source of truth every surface (API, PDF, email,
        dashboard, insights, assistant) displays -- see
        app.effective_status.get_effective_payment_status. Computed here,
        as a plain property alongside customer_name, so it's included
        automatically wherever an Invoice is serialized via
        from_attributes, with no separate computation step at each call
        site."""
        from app.effective_status import get_effective_payment_status
        from app.org_time import get_organization_today

        today_local = get_organization_today(self.organization)
        return get_effective_payment_status(self, today_local)


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (Index("ix_invoice_line_items_product_id", "product_id"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    invoice_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Purely an analytics tag ("which catalog item generated this line") --
    # NEVER read back to reconstruct description/unit_price/line_total.
    # Nullable and ON DELETE SET NULL so a hypothetical product removal
    # can never cascade into deleting invoice history; description/
    # quantity/unit_price/line_total above are already a full, permanent
    # snapshot regardless of what this FK points to (see app.services.
    # products / app.services.invoices for why this is never re-derived).
    product_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")
    product: Mapped["Product | None"] = relationship()


class Product(Base):
    """A reusable catalog entry ("template") for invoice line items --
    NOT inventory: no stock, no suppliers, no purchase orders. Selecting a
    product prefills a new invoice line's description/unit_price/currency,
    but the line always stores its own snapshot (see InvoiceLineItem
    above) -- changing or archiving a product here can never alter a
    previously issued invoice.
    """

    __tablename__ = "products"
    __table_args__ = (Index("ix_products_org_active", "organization_id", "active"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ProductType.service.value,
        server_default=ProductType.service.value,
    )
    # App-level, per-organization soft key only -- no DB uniqueness,
    # matching Customer.tax_id's exact precedent (duplicate detection is
    # an application concern; see app.services.products / app.imports.products).
    sku: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    default_unit_price: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    # Resolved from the organization's current currency at creation time
    # (see app.currency.get_currency_code) and editable afterward via
    # PATCH -- it does not silently track the org's default the way
    # nothing else pinned in this app does either.
    currency_code: Mapped[str] = mapped_column(
        String(8), nullable=False, default="USD", server_default="USD"
    )
    # A fraction (0..1), matching InvoiceCreateRequest.tax_rate's own
    # bounds -- stored on the catalog item as a convenience default only;
    # invoices remain single, invoice-level-tax_rate (see
    # app.services.invoices.compute_invoice_totals, which never reads
    # this column). The frontend may prefill a new invoice's tax field
    # from this value; nothing server-side depends on it.
    default_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=0, server_default="0"
    )
    # The only "removal" mechanism -- there is no DELETE endpoint for
    # products. Archiving just hides a product from the default catalog
    # view and the invoice-line autocomplete; it is never actually
    # removed, so a product referenced by an invoice can never be
    # physically deleted out from under that invoice's history.
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(back_populates="products")


class InvoiceReminder(Base):
    """One reminder-delivery attempt -- this row's existence, keyed by the
    unique constraint below, IS the idempotency guarantee: claiming a
    reminder is inserting this row, and a conflicting insert (someone else
    already claimed the same invoice/type/date) is how double-sends are
    prevented under concurrency, not an in-memory check. See
    app/services/invoices.py's claim/revalidate/send/update sequence and
    app/jobs/send_due_invoice_reminders.py.

    No email body is stored here -- only metadata needed for the audit
    trail and for preventing duplicates. Never contains API keys.
    """

    __tablename__ = "invoice_reminders"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "reminder_type",
            "scheduled_for_date",
            name="uq_invoice_reminder_idempotency",
        ),
        Index("ix_invoice_reminders_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    reminder_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # e.g. 3 for "3 days before due", 7 for "7 days overdue"; null for
    # due_today and manual reminders, where a day count isn't meaningful.
    days_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Part of the uniqueness key -- the calendar date (organization-local)
    # this reminder logically belongs to, not when it was actually sent.
    scheduled_for_date: Mapped[date] = mapped_column(Date, nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ReminderStatus.pending.value,
        server_default=ReminderStatus.pending.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Who initiated this reminder -- distinct from reminder_type (which
    # describes *when* relative to the due date). "scheduled" for the
    # nightly job; "manual_button"/"assistant" both use reminder_type
    # "manual" and therefore share one idempotency slot per invoice per day.
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False)
    # Reserved for future use -- EmailSender.send() doesn't currently
    # return a provider message id, so this is always NULL today. Kept as
    # a column now so a future EmailSender extension doesn't need a new
    # migration.
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
    invoice: Mapped["Invoice"] = relationship(back_populates="reminders")


class Quote(Base):
    """A proposed, pre-invoice estimate -- mirrors Invoice's field/
    relationship conventions almost exactly (see Invoice above), so it can
    be built, PDF'd, emailed, and converted by reusing invoice
    infrastructure rather than duplicating it. Line items snapshot their
    own description/quantity/unit_price/line_total exactly like
    InvoiceLineItem, for the same immutability reason.

    converted_invoice_id is the ONLY link between a quote and the invoice
    it produced -- one-directional (quote -> invoice), set once at
    conversion time and never the other way around. The invoice created
    from a quote never stores a reference back to it (see
    app.services.quotes.convert_quote_to_invoice), which is what makes
    both immutability guarantees trivial: editing the quote afterward can
    never reach the invoice, and editing the invoice can never reach the
    quote.
    """

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("organization_id", "quote_number"),
        Index("ix_quotes_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    quote_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Stored directly (unlike Invoice, which only keeps the resulting
    # tax_amount) -- duplicate_quote_record and convert_quote_to_invoice
    # both need to reproduce the exact same rate, not just its dollar
    # result at the original subtotal.
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=QuoteStatus.draft.value,
        server_default=QuoteStatus.draft.value,
    )
    # Permanently pinned at creation time -- same rationale as
    # Invoice.currency_code/Invoice.language.
    currency_code: Mapped[str] = mapped_column(
        String(8), nullable=False, default="USD", server_default="USD"
    )
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Archive/restore flag -- mirrors Product.active exactly (hide/show,
    # never destructive). The separate, narrower DELETE endpoint only ever
    # applies to status == "draft" quotes (see app.services.quotes); this
    # flag is the only "removal" mechanism for anything past draft.
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Deliberately stored raw, not hashed -- see app/quote_public_links.py's
    # module docstring for why a durable, reusable share link can't use the
    # one-time-token hash-at-rest pattern the way password reset does.
    public_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    converted_invoice_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Snapshot of the billed customer's own fields, taken at creation time
    # (app.services.quotes.create_quote_record) -- see Invoice's
    # identical columns for the full rationale; a quote later converted
    # into an invoice forwards THIS snapshot into the new invoice (see
    # convert_quote_to_invoice), never a fresh live read of the customer,
    # so a customer edited between quote creation and conversion still
    # can't retroactively alter either document.
    customer_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_email_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customer_address_snapshot: Mapped[str | None] = mapped_column(String(512), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="quotes")
    customer: Mapped["Customer | None"] = relationship()
    created_by_user: Mapped["User | None"] = relationship()
    converted_invoice: Mapped["Invoice | None"] = relationship()
    line_items: Mapped[list["QuoteLineItem"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["QuoteReminder"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan"
    )

    @property
    def customer_name(self) -> str | None:
        if self.customer_name_snapshot is not None:
            return self.customer_name_snapshot
        return self.customer.name if self.customer is not None else None

    @property
    def customer_phone(self) -> str | None:
        if self.customer_phone_snapshot is not None:
            return self.customer_phone_snapshot
        return self.customer.phone if self.customer is not None else None

    @property
    def effective_status(self) -> "QuoteStatus":
        """The single source of truth every surface displays -- see
        app.quote_effective_status.get_effective_quote_status. A plain
        property, alongside customer_name, so it's included automatically
        wherever a Quote is serialized via from_attributes."""
        from app.org_time import get_organization_today
        from app.quote_effective_status import get_effective_quote_status

        today_local = get_organization_today(self.organization)
        return get_effective_quote_status(self, today_local)

    @property
    def public_url(self) -> str:
        from app.quote_public_links import build_quote_public_link

        return build_quote_public_link(self.public_token)


class QuoteLineItem(Base):
    __tablename__ = "quote_line_items"
    __table_args__ = (Index("ix_quote_line_items_product_id", "product_id"),)

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    quote_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Purely an analytics tag -- see InvoiceLineItem.product_id's identical
    # docstring; never read back to reconstruct a line's snapshot values.
    product_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )

    quote: Mapped["Quote"] = relationship(back_populates="line_items")
    product: Mapped["Product | None"] = relationship()


class QuoteReminder(Base):
    """One reminder-delivery attempt for a quote nearing its expiry date --
    mirrors InvoiceReminder's exact idempotency shape (see that class's
    docstring): this row's existence, keyed by the unique constraint below,
    IS the idempotency guarantee. No `reminder_type` column is needed --
    quotes only ever have one reminder kind ("before_expiry"), unlike
    invoices' before/on/after-due variety."""

    __tablename__ = "quote_reminders"
    __table_args__ = (
        UniqueConstraint(
            "quote_id", "scheduled_for_date", name="uq_quote_reminder_idempotency"
        ),
        Index("ix_quote_reminders_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    quote_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    days_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_for_date: Mapped[date] = mapped_column(Date, nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ReminderStatus.pending.value,
        server_default=ReminderStatus.pending.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
    quote: Mapped["Quote"] = relationship(back_populates="reminders")


class AssistantAction(Base):
    """A single AI-proposed business action: its lifecycle (proposed ->
    executed/cancelled/expired/failed) IS the audit trail — there is
    deliberately no separate audit-log table. `input_payload` holds the
    already-validated, already-resolved tool input (e.g. a resolved
    customer_id, never a raw model-provided name or an unvalidated
    argument) as a JSON string; `summary` holds the safe, user-facing
    values shown at proposal time and re-shown identically at confirm
    time. Neither ever contains API keys, prompts, or raw conversation
    text — see app/ai/tools/.
    """

    __tablename__ = "assistant_actions"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    action_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AssistantActionStatus.proposed.value,
        server_default=AssistantActionStatus.proposed.value,
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WhatsAppIdentity(Base):
    """Links one real WhatsApp phone number to exactly one (organization,
    user) pair -- see docs/whatsapp.md's "Phone identity and linking"
    section for the full security rationale. A phone number is NEVER
    itself authentication: every inbound message is only ever attributed
    to `user_id` after this row is found with status == verified, and
    every other check (active user, active membership, active
    organization, RBAC, plan capability) still runs on top, exactly as it
    would for a browser request from that same user.

    `(provider, normalized_phone_number)` is globally unique, not scoped
    to organization_id -- this experimental phase runs exactly one shared
    WhatsApp Web session for the whole deployment (see
    app.whatsapp.provider_base's own module docstring), so one physical
    phone number can only ever correspond to one (organization, user) pair
    system-wide. A person who is a member of two organizations needs two
    separate WhatsApp-capable numbers to link both -- a documented,
    deliberate limitation of this MVP, not an oversight.

    A row is never deleted: revoking access flips `status` to `disabled`
    (see WhatsAppIdentityStatus), preserving the historical fact that this
    phone was once linked, for audit purposes.
    """

    __tablename__ = "whatsapp_identities"
    __table_args__ = (
        UniqueConstraint("provider", "normalized_phone_number", name="uq_whatsapp_identity_phone"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # E.164-ish normalized form (see app.whatsapp.security.normalize_phone_number)
    # -- the raw, as-entered value is never stored; only ever the normalized
    # comparison key, so two differently-formatted entries of the same real
    # number can never create two rows.
    normalized_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=WhatsAppIdentityStatus.pending.value,
        server_default=WhatsAppIdentityStatus.pending.value,
    )
    # Hash only -- the raw one-time code is never persisted anywhere (see
    # app.whatsapp.security.hash_verification_code), same principle as
    # app.tokens for password-reset/email-verification tokens.
    verification_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Wrong-code guesses against the current pending code, reset to 0 every
    # time a fresh code is issued -- capped by WHATSAPP_MAX_VERIFY_ATTEMPTS
    # (see app.whatsapp.service), never allowed to grow unbounded.
    verification_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship()
    user: Mapped["User"] = relationship()


class WhatsAppInboundMessage(Base):
    """Idempotency ledger + safe audit metadata for every inbound WhatsApp
    message the bridge forwards to FastAPI (Phase 23). Two distinct jobs,
    one row each:

    1. Idempotency/replay protection: `(provider, message_id)` is unique,
       checked BEFORE any processing -- a message the bridge (or a
       misbehaving/duplicate WhatsApp delivery) posts twice is processed
       at most once. Never trusts the bridge alone to dedupe.
    2. Safe channel metadata (never message content): provider, which
       identity/org/user handled it, what kind of command it resolved to,
       and whether it succeeded -- exactly the fields docs/whatsapp.md's
       "Event and audit integration" section calls for. Deliberately
       excludes raw message text, transcribed voice text, and any AI
       provider output -- this table is metadata-only, never a
       conversation transcript.

    Also the source of the `monthly_whatsapp_actions` quota (see
    app.services.organization_usage.count_whatsapp_actions_current_month):
    every row with status='processed' counts, regardless of whether the
    command was read-only or went on to create an AssistantAction (that
    narrower AI-specific quota is max_ai_actions_per_month, unchanged).
    """

    __tablename__ = "whatsapp_inbound_messages"
    __table_args__ = (
        UniqueConstraint("provider", "message_id", name="uq_whatsapp_inbound_message"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    whatsapp_identity_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("whatsapp_identities.id", ondelete="SET NULL"), nullable=True
    )
    message_type: Mapped[str] = mapped_column(String(16), nullable=False)  # text|audio
    # A safe, closed-vocabulary label -- e.g. "list_invoices", "create_invoice",
    # "confirm", "cancel", "link_verify", "help" -- never the raw message text.
    command_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization | None"] = relationship()
    user: Mapped["User | None"] = relationship()
    whatsapp_identity: Mapped["WhatsAppIdentity | None"] = relationship()


class PlatformAuditLog(Base):
    """One row per platform-administration mutation (see
    app.platform_audit_action.PlatformAuditAction) -- append-only, exactly
    like AssistantAction's own lifecycle-as-audit-trail philosophy above,
    except here there is no lifecycle to piggyback on (a suspend/reactivate
    is a single instantaneous action), so a dedicated table is the minimum
    that satisfies "who did what, to which org, and why."

    actor_email, target_organization_name, and target_user_email are
    snapshots, not joins -- mirrors OrganizationInvitation.created_by_email's
    exact rationale: the record must stay meaningful even if the acting
    user or the target organization/user is later deleted (every FK here
    is ON DELETE SET NULL, never CASCADE, so a deletion elsewhere can
    never silently erase audit history). No route ever updates or deletes
    a row here.

    Exactly one of target_organization_id/target_user_id is populated per
    row, depending on the action (Phase 13D's organization actions vs.
    Phase 13E's user-management actions) -- never both. The *_name/*_email
    snapshot for whichever target type doesn't apply is left at its
    default ("" for target_organization_name, NULL for target_user_email)
    rather than making target_organization_name nullable, which would
    require an unsupported SQLite column-constraint change; "" already
    means "not applicable" in this codebase (see Customer.tax_id).

    details is an optional JSON-encoded string (e.g. {"old_role": ...,
    "new_role": ...} for a platform-role change) -- a plain TEXT column,
    not a native JSON type, so this works identically on SQLite and
    Postgres without a dialect-specific column type.
    """

    __tablename__ = "platform_audit_log"
    __table_args__ = (
        Index("ix_platform_audit_log_target_org", "target_organization_id"),
        Index("ix_platform_audit_log_target_user", "target_user_id"),
    )

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_organization_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    target_organization_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


PLATFORM_SETTINGS_SINGLETON_ID = "platform_settings"


class PlatformSettings(Base):
    """The single row of dynamic, runtime-editable global application
    behavior (see app.services.platform_settings for how it's read and
    written) -- deliberately NOT arbitrary JSON key/value storage: every
    field here is a real, typed column with its own validation and its
    own enforcement point, exactly like every other setting in this app.

    Enforced as a true singleton by using a fixed, non-random primary key
    (PLATFORM_SETTINGS_SINGLETON_ID) rather than a generated UUID -- "does
    a row with this exact id exist yet" is a trivially safe idempotent
    check, unlike "is there already any row in this table" under
    concurrent first-reads. Lazily created on first read with these
    column defaults; there is no migration-time INSERT.

    Infrastructure configuration (AI/email provider credentials, CORS
    origins) deliberately has NO column here -- it stays environment-only
    and read-only, surfaced in GET /admin/settings as derived status
    booleans (see app.routers.platform_admin), never persisted or
    editable through this table.
    """

    __tablename__ = "platform_settings"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registrations_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    emails_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    invoice_reminders_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quote_reminders_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    default_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Optimistic-concurrency token for PATCH /admin/settings -- callers
    # must supply the version they last read as expected_version; the
    # update is applied via a single conditional
    # `UPDATE ... WHERE id = ... AND version = expected_version`
    # (see app.routers.platform_admin.update_platform_settings), never by
    # reading this value into Python and writing it back unconditionally.
    # That conditional UPDATE's rowcount, not this column's presence
    # alone, is what makes concurrent PATCHes safe.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OrganizationApiKey(Base):
    """One organization-scoped credential for the public REST API (see
    app.api_key_auth / app/routers/api_v1) -- deliberately separate from
    the browser session model (User + JWT): a key authenticates as "this
    organization, with these scopes," never as a specific human user.

    The complete secret exists only once, at creation/rotation time, in
    the response body -- never persisted, never logged, never
    recoverable afterward. Only `prefix` (a plaintext lookup key, not a
    secret on its own) and `hashed_secret` (SHA-256, see app.api_keys)
    are stored. See app.api_keys's module docstring for the full key
    format and the rationale for a fast hash over bcrypt here.

    `status` is deliberately NOT a column -- see app.api_key_status:
    effective status is always derived from revoked_at/expires_at, the
    same "one source of truth, never a redundant flag" principle
    Product.active already follows for this codebase's other lifecycle
    states.

    `permissions` is a JSON-encoded list of app.api_key_permissions
    .ApiKeyPermission values -- a plain TEXT column, not a native JSON
    type, matching PlatformAuditLog.details's exact portability
    rationale (works identically on SQLite and Postgres).

    Rotation (see app.services.organization_api_keys.rotate_api_key)
    revokes this row and creates a brand new one -- it never mutates an
    existing row's prefix/hashed_secret in place, so a key's own history
    (created_at, last_used_at up to the moment of rotation) is preserved
    exactly as it happened, never rewritten.
    """

    __tablename__ = "organization_api_keys"
    __table_args__ = (Index("ix_organization_api_keys_organization", "organization_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    prefix: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    hashed_secret: Mapped[str] = mapped_column(String(64), nullable=False)
    permissions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    organization: Mapped["Organization"] = relationship()


class OrganizationApiKeyAuditLog(Base):
    """Append-only audit trail for API-key lifecycle and authentication
    events (see app.services.organization_api_key_audit) -- deliberately
    separate from PlatformAuditLog, which is scoped exclusively to
    platform-admin (super-admin) actions and requires a User actor for
    every row. Neither of those holds for this table: its actor is an
    organization member OR nothing at all (an authentication failure,
    e.g. a revoked/expired key being presented, has no authenticated
    actor by definition), and its audience is the organization itself,
    not platform staff.

    api_key_id is nullable + ON DELETE SET NULL (matching every other
    audit-adjacent FK in this codebase) so a row about a key that no
    longer exists still means something -- but keys are never hard
    deleted in practice (see OrganizationApiKey's own docstring: rotation
    revokes, never deletes), so this is a safety net, not the normal
    path. actor_user_id is nullable for the same reason (auth failures).
    """

    __tablename__ = "organization_api_key_audit_log"
    __table_args__ = (Index("ix_org_api_key_audit_log_organization", "organization_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("organization_api_keys.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WebhookEndpoint(Base):
    """One organization-configured outbound webhook target (see
    app.services.webhook_endpoints) -- analogous in spirit to
    OrganizationApiKey, but the trust direction is reversed: an API key is
    a credential THIS app verifies on an INBOUND request, while
    `hashed_secret` here signs OUTBOUND requests this app sends, so a
    receiving endpoint can verify authenticity (see app.webhook_signing).

    Two independent lifecycle flags, matching the two independent actions
    the management UI exposes:
      - `enabled` -- pause/resume. A disabled endpoint receives no new
        automatic deliveries, but its history is untouched and it can be
        re-enabled at any time (mirrors Product.active's "hide, never
        destroy" philosophy, just named for its own domain).
      - `active` -- archive/restore. An archived endpoint is hidden from
        the default management list and is treated exactly like disabled
        for delivery purposes, but represents "this integration is being
        removed," not "temporarily paused." Never a hard delete: the
        WebhookDelivery history rows this endpoint produced must remain
        meaningful (WebhookDelivery.endpoint_id would otherwise dangle),
        and rotation history (`last_rotated_at`) stays inspectable.

    `subscribed_events` is a JSON-encoded list of app.webhook_event_type
    .WebhookEventType values, OR the single-element list `["*"]` meaning
    "every event type, including ones added in the future" -- a plain TEXT
    column, matching OrganizationApiKey.permissions's exact portability
    rationale (works identically on SQLite and Postgres).

    Unlike OrganizationApiKey.hashed_secret, `secret` is stored in a form
    this server can read back, NOT a one-way hash -- see
    app.webhook_signing's module docstring for why: an API key is only
    ever verified by comparison (inbound), so a hash is strictly correct
    and more secure, but a webhook secret must be used to COMPUTE a fresh
    HMAC signature on every future OUTBOUND delivery, indefinitely, which
    is structurally impossible from a one-way hash. This mirrors how
    Stripe/GitHub/Slack all handle webhook signing secrets. This app has
    no field-level encryption-at-rest utility anywhere yet (email
    provider credentials are environment variables, not DB columns), so
    this value's only protection is the same database-access boundary
    every other sensitive column already relies on -- documented here
    honestly as a residual limitation rather than silently implied to be
    hashed like an API key. The application layer never re-exposes it
    through any GET/list response after creation/rotation, matching
    OrganizationApiKey's "shown once" UX even though, unlike an API key,
    the value IS technically recoverable server-side (it has to be, to
    keep signing future deliveries).

    Rotation (app.services.webhook_endpoints.rotate_endpoint_secret)
    overwrites `secret` in place (unlike OrganizationApiKey rotation,
    which creates a new row) because, per this phase's explicit design
    decision, only ONE secret is ever active at a time -- there is no
    overlap window where both an old and a new secret verify successfully,
    so mutating in place is correct and simpler than OrganizationApiKey's
    revoke-and-recreate shape.
    """

    __tablename__ = "webhook_endpoints"
    __table_args__ = (Index("ix_webhook_endpoints_organization", "organization_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    subscribed_events: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_by: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()


class WebhookEvent(Base):
    """One immutable, point-in-time domain event (see
    app.services.webhook_events.record_webhook_event) -- created in the
    exact same DB transaction as the business mutation that caused it, so
    it either commits with that mutation or never exists at all (true
    same-transaction atomicity, no separate outbox table needed since this
    row already lives inside the caller's own transaction).

    `payload` is a JSON-encoded, fully-resolved snapshot at the moment the
    event fired -- deliberately never a lazy reference (e.g. "look up
    invoice X yourself") that could later resolve to different data or a
    since-deleted row. Every WebhookDelivery for this event reuses this
    exact payload on every attempt, including a manual resend, so a
    receiver always sees the state as it was at the moment the thing
    actually happened, not as it is now.

    Never updated or deleted by any code path -- `id` is the stable value
    every consumer is expected to dedupe on (see this app's own at-least-
    once delivery guarantee, documented in
    app.services.webhook_deliveries).
    """

    __tablename__ = "webhook_events"
    __table_args__ = (
        Index("ix_webhook_events_organization_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship()


class WebhookDelivery(Base):
    """One delivery attempt of one WebhookEvent to one WebhookEndpoint --
    created as `pending` in the SAME transaction as its WebhookEvent (see
    record_webhook_event), then updated exactly once, out-of-band, by
    app.services.webhook_deliveries after the actual HTTP attempt
    completes (success or failure). Never re-used for a second attempt:
    a manual resend (app.services.webhook_deliveries.resend_delivery)
    always creates a brand-new row referencing the same `event_id` --
    this row's own history (its original attempted_at/response) is never
    overwritten, matching OrganizationApiKey's "rotate creates a new row,
    never rewrites the old one" precedent.

    `request_url`/`request_headers` are snapshots taken at send time --
    NOT re-derived from the live WebhookEndpoint row later, so a
    subsequent URL edit or secret rotation on the endpoint can never alter
    what an already-recorded delivery claims was actually sent.

    `next_retry_at` is metadata only, per this phase's explicit scope
    boundary -- it is computed and stored on a failed delivery (a fixed
    backoff schedule) but nothing in this codebase ever reads it to
    actually perform a retry. It exists so a future Phase 15C worker has
    something to query against without a schema change.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_organization_created", "organization_id", "created_at"),
        Index("ix_webhook_deliveries_event", "event_id"),
        Index("ix_webhook_deliveries_endpoint", "endpoint_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("webhook_events.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    trigger: Mapped[str] = mapped_column(
        String(16), nullable=False, default="automatic", server_default="automatic"
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    request_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    request_headers: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship()
    event: Mapped["WebhookEvent"] = relationship()
    endpoint: Mapped["WebhookEndpoint"] = relationship()


class WebhookAuditLog(Base):
    """Append-only audit trail for webhook-endpoint lifecycle actions
    (create/update/enable/disable/rotate-secret/archive/manual-resend) --
    deliberately separate from PlatformAuditLog (platform-admin only) and
    a sibling, not a reuse, of OrganizationApiKeyAuditLog: mirrors that
    table's exact shape (nullable actor/target FKs, ON DELETE SET NULL,
    optional JSON `details` string) for the same reasons -- this table's
    actor is an organization member, its audience is the organization
    itself, and every FK must survive the referenced row's own deletion
    without losing the row's meaning. Kept as its own table rather than
    generalizing OrganizationApiKeyAuditLog because the two audit trails
    have no natural shared query pattern (nobody lists "all API-key AND
    webhook events together") and a shared table would need a
    discriminator column plus nullable FKs to two different resource
    types for no real benefit.
    """

    __tablename__ = "webhook_audit_log"
    __table_args__ = (Index("ix_webhook_audit_log_organization", "organization_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("webhook_endpoints.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditEntry(Base):
    """One immutable, point-in-time record of a domain event already
    raised through app.notifications.service.emit_event (see Phase 22 --
    docs/audit_timeline.md) -- the audit subsystem is just another
    consumer inside that function's existing fan-out, alongside the
    webhook/notification/email channels, never a second call site that
    reacts to a business mutation directly.

    Deliberately NOT the same table as PlatformAuditLog (platform-ADMIN
    mutations on organizations/users -- a different, privileged,
    cross-tenant surface) or WebhookAuditLog (webhook-ENDPOINT lifecycle
    actions like create/rotate-secret -- a narrow configuration trail).
    AuditEntry is the tenant-facing record of ordinary business-domain
    events (customer/product/quote/invoice/... lifecycle transitions),
    one row per emit_event call, queryable by the organization's own
    members.

    `event_type` reuses app.webhook_event_type.WebhookEventType's string
    values verbatim -- the single canonical event catalog, never a second
    enum.

    `actor_user_id` is nullable, ON DELETE SET NULL (mirrors
    WebhookAuditLog's own actor FK exactly): many events have no human
    actor -- a scheduled reminder job sending a quote, a public/anonymous
    quote accept/reject, a public-API-key-authenticated mutation -- and
    None is the honest value for "no user performed this," never a
    fabricated system-user id.

    `metadata_json` is a JSON-encoded TEXT column (the Python attribute is
    deliberately not named `metadata`, which collides with
    DeclarativeBase's own reserved `Base.metadata` attribute) holding the
    exact same payload emit_event's caller already built for the webhook
    channel -- stored a second time here, not re-derived via a join to
    WebhookEvent, so this row stays a faithful, standalone snapshot even
    if the corresponding WebhookEvent row is ever pruned independently.

    Never updated or deleted by any code path -- immutable, exactly like
    WebhookEvent's own "never updated" precedent.
    """

    __tablename__ = "audit_entries"
    __table_args__ = (
        Index("ix_audit_entries_organization_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship()


class BackgroundJob(Base):
    """One durable unit of asynchronous work -- the entire Phase 15C job
    queue lives in this single table (see app.services.background_jobs
    for enqueue/claim/lease/recovery, and app.jobs.registry for the
    closed, server-side job-type vocabulary this row's `job_type` must
    belong to). This table IS the durable dispatch mechanism: a row
    persisted in the same transaction as a business mutation (see
    app.services.webhook_events.record_webhook_event) is what replaces
    Phase 15B's non-durable Session.after_commit + ThreadPoolExecutor
    chain -- if the transaction that adds this row never commits, the
    job never existed, exactly like WebhookEvent/WebhookDelivery.

    `payload` is a JSON-encoded, schema-validated (per job_type, see
    app.jobs.registry) string -- never a pickle, never a Python callable,
    never an import path. It contains only IDs and small validated data
    (e.g. `{"delivery_id": "..."}` for webhook.deliver); a handler always
    re-fetches and re-validates the referenced rows itself rather than
    trusting anything embedded here, exactly like AssistantAction
    .input_payload's own "already-validated, already-resolved" contract.

    `organization_id` is nullable -- most jobs today (webhook delivery)
    are tenant-scoped, but the column exists to support a future
    platform-wide job (e.g. a maintenance sweep) without a schema change.
    It is never used for authorization by the worker itself (the worker
    is an internal trusted process operating across all tenants by
    design); it exists purely for Platform Admin filtering/observability.

    Claim/lease fields (`claimed_at`, `claimed_by`, `lease_expires_at`)
    are the ONLY source of truth for "who currently owns this job" -- see
    app.services.background_jobs.claim_jobs for the atomic conditional
    UPDATE that sets them, and recover_abandoned_jobs for how an expired
    lease returns a row to an executable state after a worker crash.

    `idempotency_key` is nullable + unique (NULL values never collide,
    per standard SQL unique-constraint semantics on both SQLite and
    Postgres) -- used to make a specific logical enqueue ("deliver this
    exact WebhookDelivery") impossible to duplicate at the database
    level, not just by an application-level check (see
    app.services.background_jobs.enqueue_job).

    `attempts`/`max_attempts` count EXECUTION attempts of this one job
    row (crash/lease-expiry resilience: how many times a worker tried
    and failed to even finish running this job before it's given up on
    entirely) -- a deliberately small, generic ceiling with no knowledge
    of any particular job type's own domain retry policy. This is NOT
    the webhook delivery backoff schedule: that's a completely separate,
    domain-level concept enforced by the webhook.retry handler itself
    (see app.jobs.handlers.webhook, which checks WebhookDelivery
    .attempt_number against its own ceiling and decides whether to chain
    another webhook.retry job) -- conflating the two would mean a worker
    crash-looping on a buggy handler and a third-party endpoint being
    down for a day would consume from the same counter, which is wrong
    for both.
    """

    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_claim_scan", "status", "queue", "available_at"),
        Index("ix_background_jobs_organization", "organization_id"),
        Index("ix_background_jobs_lease", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.pending.value, server_default=JobStatus.pending.value
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    queue: Mapped[str] = mapped_column(String(32), nullable=False, default="default", server_default="default")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organization: Mapped["Organization | None"] = relationship()


class Notification(Base):
    """One in-app notification addressed to one organization member --
    created for EVERY active member of the organization the moment a
    domain event is emitted (see app.notifications.service.emit_event),
    unconditionally, with no per-user opt-out: every member's inbox
    should reflect what actually happened in their organization,
    regardless of their email preference (see NotificationPreference,
    which only ever governs the EMAIL channel). This mirrors
    WebhookEvent's own "recorded regardless of subscription" precedent.

    `title`/`body` are a frozen, point-in-time rendering of the event
    (see app.notifications.copy) -- never re-derived later, exactly like
    WebhookEvent.payload, so a future change to notification copy
    templates can never alter the text of an already-delivered
    notification.

    `event_id` is a debugging/cross-reference pointer back to the single
    WebhookEvent this notification (and any resulting notification.email
    job) was generated from -- see that table's own docstring for why it
    is the one durable, fully-resolved snapshot every channel reads from.
    ON DELETE SET NULL is defensive schema hygiene only: WebhookEvent rows
    are, by their own contract, never actually deleted.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("webhook_events.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship()


class NotificationPreference(Base):
    """Per-user, per-organization opt-out of the EMAIL notification
    channel only -- in-app notifications (see Notification above) are
    always created for every active member and cannot be disabled; this
    row exists purely to stop receiving emails about them. Created
    lazily, only when a user actually changes the default away from
    email_enabled=True (see app.notifications.service.is_email_enabled)
    -- the absence of a row means the default, exactly like
    ProviderCustomer's own lazy-row-creation precedent from the billing
    domain.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    run_startup_migrations(engine)
