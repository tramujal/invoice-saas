import uuid
from datetime import date, datetime
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
from app.payment_status import PaymentStatus
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

    members: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organization"
    )
    customers: Mapped[list["Customer"]] = relationship(back_populates="organization")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="organization")


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
        back_populates="user"
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

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped["Organization"] = relationship(back_populates="members")


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

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")


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
