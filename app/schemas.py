from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.limits import (
    AI_MAX_HISTORY_MESSAGE_LENGTH,
    AI_MAX_HISTORY_MESSAGES,
    AI_MAX_HISTORY_TOTAL_CHARS,
    AI_MAX_USER_MESSAGE_LENGTH,
)
from app.customer_validation import is_valid_email_format
from app.insights.limits import (
    INSIGHTS_MAX_MESSAGE_LENGTH,
    INSIGHTS_MAX_SUGGESTION_LENGTH,
    INSIGHTS_MAX_TITLE_LENGTH,
)
from app.invoice_numbering import format_invoice_number
from app.membership_role import InvitationRole, MembershipRole
from app.payment_status import PaymentStatus
from app.product_type import ProductType
from app.quote_numbering import format_quote_number
from app.quote_status import QuoteStatus
from app.reminder_settings import (
    REMINDER_DAY_LIST_MAX_LENGTH,
    REMINDER_DAY_MAX,
    REMINDER_DAY_MIN,
    parse_day_list,
)
from app.reminder_type import ReminderType
from app.security import PASSWORD_POLICY_MESSAGE, password_meets_policy

_VALID_TIMEZONES = available_timezones()


class SortDirection(str, Enum):
    asc = "asc"
    desc = "desc"


class InvoiceSortField(str, Enum):
    invoice_number = "invoice_number"
    created_at = "created_at"
    total = "total"
    customer_name = "customer_name"


class QuoteSortField(str, Enum):
    quote_number = "quote_number"
    created_at = "created_at"
    total = "total"
    customer_name = "customer_name"
    expiry_date = "expiry_date"


class InvoiceDueFilter(str, Enum):
    """A due-date bucket, distinct from and combinable with the existing
    payment_status filter -- see app.effective_status for the same
    due-date-driven definition of "overdue" used everywhere else."""

    overdue = "overdue"
    due_soon = "due_soon"
    no_due_date = "no_due_date"


class CustomerSortField(str, Enum):
    name = "name"
    email = "email"
    created_at = "created_at"


class ProductSortField(str, Enum):
    name = "name"
    created_at = "created_at"
    default_unit_price = "default_unit_price"


class OrganizationLanguage(str, Enum):
    en = "en"
    es = "es"


class CurrencyCode(str, Enum):
    USD = "USD"
    UYU = "UYU"
    EUR = "EUR"


class TaxLabelOption(str, Enum):
    tax_id = "Tax ID"
    rut = "RUT"
    cuit = "CUIT"
    nif = "NIF"


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("Invalid email address")
    return value


def _format_invoice_number(value: int | str) -> str:
    if isinstance(value, str):
        return value
    return format_invoice_number(value)


def _blank_to_none(value: str | None) -> str | None:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _validate_password(value: str) -> str:
    """Shared by RegisterRequest and ResetPasswordRequest so the password
    policy has exactly one implementation (app.security.password_meets_policy)
    rather than being checked twice and risking drift."""
    if not password_meets_policy(value):
        raise ValueError(PASSWORD_POLICY_MESSAGE)
    return value


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(max_length=72)
    organization_name: str = Field(min_length=1, max_length=255)
    # Public/marketing-page language the visitor was viewing when they
    # registered, used only to localize the verification email — same role
    # as ForgotPasswordRequest.language. Does not set Organization.language
    # (that stays the real, changeable-in-Settings default).
    language: OrganizationLanguage = OrganizationLanguage.en

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def check_password_policy(cls, value: str) -> str:
        return _validate_password(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    # Public/marketing-page language the user was viewing when they
    # submitted this form, used to localize the reset email. Defaults to
    # English so older clients that don't send it still work.
    language: OrganizationLanguage = OrganizationLanguage.en

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class ForgotPasswordResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(max_length=72)

    @field_validator("new_password")
    @classmethod
    def check_password_policy(cls, value: str) -> str:
        return _validate_password(value)


class ResetPasswordResponse(BaseModel):
    message: str


class ResendVerificationResponse(BaseModel):
    message: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class VerifyEmailResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    email_verified: bool


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    currency_code: str
    language: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    organizations: list[OrganizationSummary]


class MeResponse(BaseModel):
    user: UserResponse
    organizations: list[OrganizationSummary]


def _check_timezone(value: str) -> str:
    if value not in _VALID_TIMEZONES:
        raise ValueError("Invalid IANA timezone identifier")
    return value


def _check_reminder_day_list(value: list[int]) -> list[int]:
    if len(value) > REMINDER_DAY_LIST_MAX_LENGTH:
        raise ValueError(
            f"At most {REMINDER_DAY_LIST_MAX_LENGTH} reminder days may be configured"
        )
    for day in value:
        if not (REMINDER_DAY_MIN <= day <= REMINDER_DAY_MAX):
            raise ValueError(
                f"Reminder days must be between {REMINDER_DAY_MIN} and {REMINDER_DAY_MAX}"
            )
    return value


class OrganizationProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    business_name: str | None
    tax_id: str | None
    address: str | None
    phone: str | None
    email: str | None
    logo_url: str | None
    language: str
    currency_code: str
    tax_label: str
    timezone: str
    reminders_enabled: bool
    reminder_before_due_days: list[int]
    reminder_on_due_date: bool
    reminder_after_due_days: list[int]
    # Independent of the invoice reminder fields above -- see
    # Organization.quote_reminders_enabled's docstring in app/models.py.
    quote_reminders_enabled: bool
    quote_reminder_before_expiry_days: list[int]

    @field_validator(
        "reminder_before_due_days",
        "reminder_after_due_days",
        "quote_reminder_before_expiry_days",
        mode="before",
    )
    @classmethod
    def _parse_stored_day_list(cls, value: str | list[int]) -> list[int]:
        # The ORM column is a comma-separated string (see
        # app.reminder_settings) -- converted to a list here so API
        # responses are a normal JSON array, never a raw stored string.
        if isinstance(value, str):
            return parse_day_list(value)
        return value


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    business_name: str | None = Field(default=None, max_length=255)
    tax_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=512)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    logo_url: str | None = Field(default=None, max_length=1024)
    language: OrganizationLanguage | None = None
    currency_code: CurrencyCode | None = None
    tax_label: TaxLabelOption | None = None
    timezone: str | None = None
    reminders_enabled: bool | None = None
    reminder_before_due_days: list[int] | None = Field(
        default=None, max_length=REMINDER_DAY_LIST_MAX_LENGTH
    )
    reminder_on_due_date: bool | None = None
    reminder_after_due_days: list[int] | None = Field(
        default=None, max_length=REMINDER_DAY_LIST_MAX_LENGTH
    )
    quote_reminders_enabled: bool | None = None
    quote_reminder_before_expiry_days: list[int] | None = Field(
        default=None, max_length=REMINDER_DAY_LIST_MAX_LENGTH
    )

    @field_validator(
        "business_name", "tax_id", "address", "phone", "email", "logo_url",
        mode="before",
    )
    @classmethod
    def _normalize_blank(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("timezone")
    @classmethod
    def _check_timezone_value(cls, value: str) -> str:
        return _check_timezone(value)

    @field_validator(
        "reminder_before_due_days",
        "reminder_after_due_days",
        "quote_reminder_before_expiry_days",
    )
    @classmethod
    def _check_day_list_value(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        return _check_reminder_day_list(value)


# --- Team / roles / invitations ---------------------------------------------


class MembershipStatusEnum(str, Enum):
    active = "active"
    removed = "removed"


class MembershipRoleUpdateRequest(BaseModel):
    """Ordinary admin/member/viewer transitions -- deliberately typed to
    InvitationRole (never MembershipRole), so this endpoint can never grant
    "owner" at all, by construction. Demoting an existing owner IS allowed
    through this same request (new_role is still admin/member/viewer);
    granting owner is only ever possible via the dedicated
    grant-ownership action below."""

    role: InvitationRole


class GrantOwnershipRequest(BaseModel):
    """Confirmation is required in the body itself, not just implied by
    hitting the endpoint -- granting ownership is the single most
    consequential action in this feature, so it gets its own explicit,
    unmistakable opt-in."""

    confirm: bool = Field(
        description="Must be true. A lightweight, explicit anti-accidental-submission guard."
    )


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: InvitationRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    user_id: str
    user_email: str
    role: MembershipRole
    status: MembershipStatusEnum
    invited_by_email: str | None
    invited_at: datetime | None
    accepted_at: datetime
    created_at: datetime
    updated_at: datetime
    # Derived from role via app.permissions.ROLE_PERMISSIONS (see
    # OrganizationMember.permissions) -- the frontend gates UI on these
    # values, never on the role name itself, so a future custom role needs
    # no frontend changes to participate correctly.
    permissions: list[str]


class PaginatedMembersResponse(BaseModel):
    total: int
    items: list[MemberResponse]


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    email: str
    role: InvitationRole
    expires_at: datetime
    accepted_at: datetime | None
    created_by_email: str | None
    created_at: datetime


class PaginatedInvitationsResponse(BaseModel):
    total: int
    items: list[InvitationResponse]


class PublicInvitationResponse(BaseModel):
    """What the anonymous accept-invitation page renders -- deliberately
    narrower than InvitationResponse: no ids, no organization_id, nothing
    beyond what a visitor needs to decide whether to accept. Mirrors
    PublicQuoteResponse's exact "narrow, public-safe subset" rationale."""

    organization_name: str
    inviter_email: str | None
    role: InvitationRole
    expires_at: datetime
    already_accepted: bool
    expired: bool


class PublicInvitationAcceptResponse(BaseModel):
    organization_id: str
    organization_name: str
    role: InvitationRole


class TeamRoleCount(BaseModel):
    role: MembershipRole
    count: int


class TeamSummaryResponse(BaseModel):
    total_members: int
    by_role: list[TeamRoleCount]
    owner_count: int
    pending_invitations: int


class InvoiceLineItemCreate(BaseModel):
    description: str = Field(min_length=1, max_length=512)
    quantity: Decimal = Field(gt=0, decimal_places=4, max_digits=14)
    unit_price: Decimal = Field(ge=0, decimal_places=2, max_digits=14)
    # Purely an analytics tag ("this line came from this catalog item") --
    # validated to resolve within the organization at creation time (see
    # create_invoice_record), but never used to re-derive description/
    # unit_price/line_total, which always come from this request as-is.
    product_id: str | None = None


class InvoiceCreateRequest(BaseModel):
    line_items: list[InvoiceLineItemCreate] = Field(min_length=1)
    tax_rate: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=1,
        description="Tax rate as a fraction, e.g. 0.1 for 10%",
    )
    customer_id: str | None = None
    # None => falls back to the organization's current currency_code at
    # creation time (see create_invoice). Once set, permanent — see
    # Invoice.currency_code.
    currency_code: CurrencyCode | None = None
    # None => no due date (matches every historical invoice). Validated
    # against the organization's local "today" server-side (see
    # create_invoice_record / due_date_before_issue_date), not here --
    # this schema has no access to the organization's timezone.
    due_date: date | None = None


class InvoiceLineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    product_id: str | None


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    invoice_number: str
    organization_id: str
    created_by_user_id: str | None
    customer_id: str | None
    customer_name: str | None
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    payment_status: PaymentStatus
    # Derived, read-only -- the single source of truth every surface
    # displays (see app.effective_status / Invoice.effective_payment_status).
    # payment_status above stays the raw, editable pending/paid toggle.
    effective_payment_status: PaymentStatus
    currency_code: str
    language: str
    due_date: date | None
    line_items: list[InvoiceLineItemResponse]

    @field_validator("invoice_number", mode="before")
    @classmethod
    def _format_number(cls, value: int | str) -> str:
        return _format_invoice_number(value)


class InvoiceSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    invoice_number: str
    customer_id: str | None
    customer_name: str | None
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    payment_status: PaymentStatus
    effective_payment_status: PaymentStatus
    currency_code: str
    language: str
    due_date: date | None
    created_at: datetime

    @field_validator("invoice_number", mode="before")
    @classmethod
    def _format_number(cls, value: int | str) -> str:
        return _format_invoice_number(value)


class InvoicePaymentStatusUpdate(BaseModel):
    # Overdue is a derived, read-only label (see effective_payment_status)
    # -- no longer a value a user can set directly. Still accepted here at
    # the type level only insofar as PaymentStatus itself still declares
    # it, but the frontend's PaymentStatusSelect no longer offers it, and
    # nothing server-side relies on it ever being submitted this way.
    payment_status: PaymentStatus


class SendInvoiceEmailResponse(BaseModel):
    sent: bool
    sent_to: str


class SendInvoiceReminderResponse(BaseModel):
    sent: bool
    sent_to: str
    reminder_type: ReminderType


class PaginatedInvoicesResponse(BaseModel):
    """Total number of invoices matching the org filter (all pages), plus one page of rows."""

    total: int
    items: list[InvoiceSummaryResponse]


def _format_quote_number(value: int | str) -> str:
    if isinstance(value, str):
        return value
    return format_quote_number(value)


class QuoteLineItemCreate(BaseModel):
    description: str = Field(min_length=1, max_length=512)
    quantity: Decimal = Field(gt=0, decimal_places=4, max_digits=14)
    unit_price: Decimal = Field(ge=0, decimal_places=2, max_digits=14)
    # Purely an analytics tag -- see InvoiceLineItemCreate.product_id's
    # identical docstring.
    product_id: str | None = None


class QuoteCreateRequest(BaseModel):
    line_items: list[QuoteLineItemCreate] = Field(min_length=1)
    tax_rate: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=1,
        description="Tax rate as a fraction, e.g. 0.1 for 10%",
    )
    customer_id: str | None = None
    currency_code: CurrencyCode | None = None
    expiry_date: date | None = None
    notes: str = Field(default="", max_length=8000)


class QuoteUpdateRequest(BaseModel):
    line_items: list[QuoteLineItemCreate] | None = Field(default=None, min_length=1)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    customer_id: str | None = None
    expiry_date: date | None = None
    notes: str | None = Field(default=None, max_length=8000)


class QuoteLineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    product_id: str | None


class QuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    quote_number: str
    organization_id: str
    created_by_user_id: str | None
    customer_id: str | None
    customer_name: str | None
    subtotal: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal
    status: QuoteStatus
    # Derived, read-only -- see app.quote_effective_status /
    # Quote.effective_status. `status` above stays the raw stored value.
    effective_status: QuoteStatus
    currency_code: str
    language: str
    issue_date: date
    expiry_date: date | None
    notes: str
    active: bool
    converted_invoice_id: str | None
    public_url: str
    created_at: datetime
    updated_at: datetime
    line_items: list[QuoteLineItemResponse]

    @field_validator("quote_number", mode="before")
    @classmethod
    def _format_number(cls, value: int | str) -> str:
        return _format_quote_number(value)


class QuoteSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    quote_number: str
    customer_id: str | None
    customer_name: str | None
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    status: QuoteStatus
    effective_status: QuoteStatus
    currency_code: str
    language: str
    issue_date: date
    expiry_date: date | None
    active: bool
    converted_invoice_id: str | None
    created_at: datetime

    @field_validator("quote_number", mode="before")
    @classmethod
    def _format_number(cls, value: int | str) -> str:
        return _format_quote_number(value)


class PaginatedQuotesResponse(BaseModel):
    total: int
    items: list[QuoteSummaryResponse]


class SendQuoteEmailResponse(BaseModel):
    sent: bool
    sent_to: str


class ConvertQuoteToInvoiceResponse(BaseModel):
    invoice_id: str
    invoice_number: str


class PublicQuoteLineItemResponse(BaseModel):
    """Same shape as QuoteLineItemResponse, minus product_id -- an
    anonymous visitor has no reason to see an internal catalog id."""

    model_config = ConfigDict(from_attributes=True)

    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class PublicQuoteResponse(BaseModel):
    """What the unauthenticated public quote page renders -- deliberately
    narrower than QuoteResponse: no organization_id, created_by_user_id,
    converted_invoice_id, or product_id anywhere. See
    app/routers/quote_public.py."""

    model_config = ConfigDict(from_attributes=True)

    quote_number: str
    organization_name: str
    customer_name: str | None
    subtotal: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal
    effective_status: QuoteStatus
    currency_code: str
    language: str
    issue_date: date
    expiry_date: date | None
    notes: str
    line_items: list[PublicQuoteLineItemResponse]

    @field_validator("quote_number", mode="before")
    @classmethod
    def _format_number(cls, value: int | str) -> str:
        return _format_quote_number(value)


class PublicQuoteActionResponse(BaseModel):
    status: QuoteStatus


def _check_customer_email_format(value: str) -> str:
    """Shared by CustomerCreateRequest/CustomerUpdateRequest and the CSV/XLSX
    importer (app.imports.customers) — see app.customer_validation for why
    this is centralized rather than re-implemented per call site."""
    if not is_valid_email_format(value):
        raise ValueError("Invalid email address")
    return value


class CustomerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    phone: str = Field(default="", max_length=64)
    address: str = Field(default="", max_length=512)
    tax_id: str = Field(default="", max_length=64)

    @field_validator("email")
    @classmethod
    def check_email_format(cls, value: str) -> str:
        return _check_customer_email_format(value)


class CustomerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=512)
    tax_id: str | None = Field(default=None, max_length=64)

    @field_validator("email")
    @classmethod
    def check_email_format(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _check_customer_email_format(value)


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=1024)
    type: ProductType = ProductType.service
    sku: str = Field(default="", max_length=64)
    default_unit_price: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2, max_digits=14)
    # None => falls back to the organization's current currency_code at
    # creation time (see create_product_record) -- same convention as
    # InvoiceCreateRequest.currency_code.
    currency_code: CurrencyCode | None = None
    default_tax_rate: Decimal = Field(
        default=Decimal("0"), ge=0, le=1, decimal_places=4, max_digits=5
    )


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    type: ProductType | None = None
    sku: str | None = Field(default=None, max_length=64)
    default_unit_price: Decimal | None = Field(
        default=None, ge=0, decimal_places=2, max_digits=14
    )
    currency_code: CurrencyCode | None = None
    default_tax_rate: Decimal | None = Field(
        default=None, ge=0, le=1, decimal_places=4, max_digits=5
    )
    # Archiving/restoring have their own dedicated endpoints (POST
    # .../archive, .../restore) rather than this field -- kept off this
    # schema so a plain profile-edit PATCH can never accidentally flip it.


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    description: str
    type: ProductType
    sku: str
    default_unit_price: Decimal
    currency_code: str
    default_tax_rate: Decimal
    active: bool
    created_at: datetime
    updated_at: datetime


class PaginatedProductsResponse(BaseModel):
    total: int
    items: list[ProductResponse]


class CurrencyRevenueSummary(BaseModel):
    """Revenue figures for one currency, never combined with any other —
    see the dashboard router for why summing across currencies never
    happens here."""

    currency_code: str
    total_revenue: Decimal
    revenue_this_month: Decimal
    revenue_last_month: Decimal
    revenue_growth_percent: Decimal | None


class DashboardResponse(BaseModel):
    total_invoices: int
    total_customers: int
    pending_invoices: int
    paid_invoices: int
    overdue_invoices: int
    # One entry per currency present among this organization's invoices —
    # deliberately not a single flat total, since a total that mixed e.g.
    # USD and UYU would be meaningless. Counts above stay flat: they're
    # counts, not money, so combining them across currencies is fine.
    revenue_by_currency: list[CurrencyRevenueSummary]
    recent_invoices: list[InvoiceSummaryResponse]


class MonthlySummaryPoint(BaseModel):
    """Invoice volume per month — currency-agnostic (a count, not money)."""

    month: str
    invoice_count: int


class MonthlyRevenuePoint(BaseModel):
    """Revenue per month, per currency. Never aggregate across
    currency_code values."""

    month: str
    currency_code: str
    revenue: Decimal


class PaymentStatusCountPoint(BaseModel):
    status: PaymentStatus
    count: int


class TopCustomerRevenue(BaseModel):
    customer_id: str
    customer_name: str
    currency_code: str
    revenue: Decimal


class TopProductRevenue(BaseModel):
    """One catalog item's ranking within one currency -- mirrors
    TopCustomerRevenue's exact per-currency-safe shape. `product_type`
    lets the frontend split this single flat list into "top products" vs
    "top services" client-side, the same way it already filters
    top_customers by currency."""

    product_id: str
    product_name: str
    product_type: str
    currency_code: str
    revenue: Decimal
    invoice_count: int


class QuoteStatusCountPoint(BaseModel):
    status: QuoteStatus
    count: int


class QuoteCurrencyPipelineSummary(BaseModel):
    """Quote pipeline figures for one currency, never combined with any
    other -- same per-currency-safe rationale as CurrencyRevenueSummary."""

    currency_code: str
    revenue_in_quotes: Decimal  # total value of all non-terminal (draft/sent) quotes
    projected_revenue: Decimal  # revenue_in_quotes weighted by this currency's acceptance rate
    accepted_this_month: int
    rejected_this_month: int
    converted_this_month: int


class QuotePipelineSummary(BaseModel):
    counts_by_status: list[QuoteStatusCountPoint]
    acceptance_rate_percent: float | None  # accepted / (accepted + rejected), all-time
    by_currency: list[QuoteCurrencyPipelineSummary]


class QuoteMonthlyConversionPoint(BaseModel):
    month: str
    converted_count: int


class DashboardAnalyticsResponse(BaseModel):
    monthly_summary: list[MonthlySummaryPoint]
    monthly_revenue_by_currency: list[MonthlyRevenuePoint]
    invoice_count_by_status: list[PaymentStatusCountPoint]
    # Top customers computed independently within each currency (a
    # customer can be "top" in USD and unranked in UYU) — entries are
    # tagged with currency_code so the frontend can filter to one
    # currency at a time without ever summing revenue across currencies.
    top_customers: list[TopCustomerRevenue]
    # Same independent-per-currency ranking, for catalog items -- see
    # TopProductRevenue.
    top_products_and_services: list[TopProductRevenue]
    quote_pipeline: QuotePipelineSummary
    quote_monthly_conversions: list[QuoteMonthlyConversionPoint]
    team: TeamSummaryResponse


class InsightMetricResponse(BaseModel):
    currency_code: str | None
    value: Decimal | None
    percentage: float | None


class InsightRelatedEntityResponse(BaseModel):
    type: Literal["invoice", "customer"] | None
    id: str | None
    label: str | None


class InsightCtaResponse(BaseModel):
    type: Literal[
        "view_overdue_invoices",
        "view_due_soon_invoices",
        "review_pending_invoices",
        "create_invoice",
        "ask_assistant",
        "view_products",
        "view_pending_quotes",
        "view_expiring_quotes",
        "view_team",
    ]
    # Only set for type == "ask_assistant" -- a deterministic, already-
    # localized prefill question, never AI-generated.
    question: str | None = None


class InsightResponse(BaseModel):
    """API-facing shape of one dashboard insight (app.insights.models.Insight,
    serialized). `title`/`message`/`suggestion` arrive already localized
    from the backend -- the frontend never translates insight content
    itself, only the surrounding chrome (see app.localization)."""

    id: str
    category: str
    severity: Literal["info", "warning", "critical", "positive"]
    tier: Literal["primary", "secondary"]
    title: str
    message: str
    suggestion: str | None
    metric: InsightMetricResponse | None
    related_entity: InsightRelatedEntityResponse | None
    cta: InsightCtaResponse | None


class DashboardInsightsResponse(BaseModel):
    generated_at: datetime
    # "deterministic" when AI narration was unavailable/disabled/invalid;
    # "ai_enhanced" when the AI's rewrite+ranking passed validation and was
    # applied. Purely informational -- the frontend renders identically
    # either way.
    source: Literal["deterministic", "ai_enhanced"]
    # Whether AI enhancement is actually configured for this deployment --
    # drives whether the frontend shows a "Refresh insights" button at all.
    ai_available: bool
    insights: list[InsightResponse]


class InsightNarrationEntry(BaseModel):
    """One insight's AI-rewritten text. Deliberately has NO numeric field
    of any kind -- title/message/suggestion are free text only, so the
    model is structurally incapable of injecting a new figure, not merely
    discouraged from it by prompt. extra="forbid" rejects the whole
    response if a model tries to sneak in e.g. a "metric" or "value" field
    anyway."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=INSIGHTS_MAX_TITLE_LENGTH)
    message: str = Field(min_length=1, max_length=INSIGHTS_MAX_MESSAGE_LENGTH)
    suggestion: str | None = Field(default=None, max_length=INSIGHTS_MAX_SUGGESTION_LENGTH)


class InsightNarrationResponse(BaseModel):
    """The AI narration tool's full argument schema -- see
    app/insights/narration.py. Every `id` referenced here (in ranked_ids or
    in a narration entry) is checked against the deterministic engine's own
    known-id set for THIS request; any unknown id invalidates the whole
    response and the caller falls back to fully deterministic output."""

    model_config = ConfigDict(extra="forbid")

    ranked_ids: list[str] = Field(max_length=32)
    narration: list[InsightNarrationEntry] = Field(max_length=32)


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    email: str
    phone: str
    address: str
    tax_id: str
    created_at: datetime
    updated_at: datetime


class AssistantHistoryMessage(BaseModel):
    """One turn of client-supplied conversation history — untrusted input.

    `role` is restricted to user/assistant at the schema level: pydantic
    itself rejects any other value (in particular "system") with a 422
    before this ever reaches application code, so there is no path by
    which a client can inject a fake system-role message into the prompt.
    """

    role: Literal["user", "assistant"]
    content: str = Field(min_length=0, max_length=AI_MAX_HISTORY_MESSAGE_LENGTH)


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=AI_MAX_USER_MESSAGE_LENGTH)
    # Optional and defaults to empty — the literal wire contract is just
    # {"message": "..."}; history is an additive extension so multi-turn
    # follow-ups ("what about last month?") actually have context, without
    # the backend storing any conversation state itself (the client resends
    # its own history every call).
    history: list[AssistantHistoryMessage] = Field(
        default_factory=list, max_length=AI_MAX_HISTORY_MESSAGES
    )

    @field_validator("history")
    @classmethod
    def _check_total_history_size(
        cls, value: list[AssistantHistoryMessage]
    ) -> list[AssistantHistoryMessage]:
        total_chars = sum(len(m.content) for m in value)
        if total_chars > AI_MAX_HISTORY_TOTAL_CHARS:
            raise ValueError("Conversation history is too large.")
        return value


class AssistantActionConfirmResponse(BaseModel):
    """Response from POST .../assistant/actions/{proposal_id}/confirm.
    `summary` is the tool's safe, user-facing result -- never a raw ORM
    object or anything containing an internal id beyond what the action
    itself already surfaces (e.g. an invoice number)."""

    status: Literal["executed"]
    action: str
    summary: dict[str, Any]


class AssistantActionCancelResponse(BaseModel):
    status: Literal["cancelled"]


class ImportPreviewRowResult(BaseModel):
    row_number: int
    status: Literal["valid", "warning", "invalid", "duplicate"]
    reason_code: str | None
    values: dict[str, str | None]


class ImportPreviewResponse(BaseModel):
    file_type: Literal["csv", "xlsx"]
    headers: list[str]
    normalized_headers: list[str]
    auto_mapping: dict[str, str]
    requires_manual_mapping: bool
    missing_required_fields: list[str]
    total_rows: int
    # Capped subset for display — see IMPORT_MAX_PREVIEW_ROWS. The full
    # file is still validated server-side; valid/warning/invalid/duplicate
    # counts below reflect ALL rows, not just the ones shown.
    preview_rows: list[ImportPreviewRowResult]
    valid_count: int
    warning_count: int
    invalid_count: int
    duplicate_count: int


class ImportConfirmRowResult(BaseModel):
    row_number: int
    status: Literal["imported", "skipped", "failed"]
    reason_code: str | None
    values: dict[str, str | None]


class ImportConfirmResponse(BaseModel):
    imported_count: int
    skipped_duplicate_count: int
    failed_count: int
    total_processed: int
    # Every row, never capped — this is the authoritative final record and
    # (client-side) error-report source, unlike preview_rows above.
    row_results: list[ImportConfirmRowResult]
