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
from app.membership_role import MembershipRole
from app.membership_status import MembershipStatus
from app.payment_status import PaymentStatus
from app.product_type import ProductType
from app.quote_status import QuoteStatus
from app.reminder_status import ReminderStatus
from app.reminder_type import ReminderType
from app.schema_migrations import run_startup_migrations


class Base(DeclarativeBase):
    pass


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

    members: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organization"
    )
    customers: Mapped[list["Customer"]] = relationship(back_populates="organization")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="organization")
    products: Mapped[list["Product"]] = relationship(back_populates="organization")
    quotes: Mapped[list["Quote"]] = relationship(back_populates="organization")


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
        return self.customer.name if self.customer is not None else None

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
        return self.customer.name if self.customer is not None else None

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


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    run_startup_migrations(engine)
