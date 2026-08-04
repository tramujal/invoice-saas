from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai.limits import (
    AI_MAX_HISTORY_MESSAGE_LENGTH,
    AI_MAX_HISTORY_MESSAGES,
    AI_MAX_HISTORY_TOTAL_CHARS,
    AI_MAX_USER_MESSAGE_LENGTH,
)
from app.api_key_permissions import ApiKeyPermission
from app.api_key_status import ApiKeyStatus
from app.customer_validation import is_valid_email_format
from app.insights.limits import (
    INSIGHTS_MAX_MESSAGE_LENGTH,
    INSIGHTS_MAX_SUGGESTION_LENGTH,
    INSIGHTS_MAX_TITLE_LENGTH,
)
from app.invoice_numbering import format_invoice_number
from app.membership_role import InvitationRole, MembershipRole
from app.organization_status import OrganizationStatus
from app.payment_status import PaymentStatus
from app.platform_permissions import PlatformRole
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
from app.user_status import UserStatus
from app.webhook_delivery_status import WebhookDeliveryStatus
from app.webhook_delivery_trigger import WebhookDeliveryTrigger
from app.webhook_event_type import WebhookEventType, event_domain

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
    # A user's own platform-administration role (see app.platform_permissions),
    # entirely independent from any organization role. NULL for every
    # ordinary user. Returned here (login/register/me all build this same
    # schema) purely so the frontend can decide whether to show the
    # Platform Admin entry point -- never used for backend authorization,
    # which always re-checks the live User.platform_role via
    # require_platform_permission, not this cached response value.
    platform_role: str | None = None


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    currency_code: str
    language: str
    # The caller's own effective permission set in this organization --
    # same computed values as OrganizationMember.permissions / see
    # MemberResponse.permissions's docstring for why the frontend must gate
    # UI on these values rather than re-deriving them from a role name.
    permissions: list[str]
    # Lets AppShell detect "the organization I'm currently in got
    # suspended" from the same /auth/me call it already makes on every
    # load -- this endpoint is deliberately not org-scoped (no
    # require_permission/require_org_member call), so it stays reachable
    # even for a suspended organization's own members, unlike every
    # org-scoped endpoint (see app.deps._ensure_organization_active).
    status: OrganizationStatus


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
    customer_phone: str | None
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
    customer_phone: str | None
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
    # The durable, shareable public accept/reject link -- same property as
    # QuoteResponse.public_url, now also on the list-row shape so row
    # actions (e.g. "Open in WhatsApp") don't need a second detail fetch.
    public_url: str
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
    # True when the caller already saw a Level 2/3 (warning) duplicate
    # dialog and explicitly chose "Create anyway" -- never required, and
    # never itself a way to bypass the Level 1 (tax_id) block, which is
    # enforced unconditionally in app.services.customers regardless of
    # this flag. Recorded on the emitted event's payload only when True
    # (see create_customer_record) -- purely an audit detail, not part of
    # the persisted Customer row.
    duplicate_warning_acknowledged: bool = False

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
    duplicate_warning_acknowledged: bool = False

    @field_validator("email")
    @classmethod
    def check_email_format(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _check_customer_email_format(value)


class CustomerDuplicateCheckRequest(BaseModel):
    """Body for POST .../customers/check-duplicates. Every field is
    optional and an empty string means "don't check this field" (see
    app.customer_duplicates.check_customer_duplicates) -- the edit flow
    relies on this to skip fields the user didn't change."""

    name: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=64)
    tax_id: str = Field(default="", max_length=64)
    # Excludes this customer from the candidate pool -- always the id of
    # the customer currently being edited, never set on create.
    exclude_customer_id: str | None = None


class CustomerDuplicateMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    customer_name: str
    email: str
    phone: str
    tax_id: str
    reasons: list[str]


class CustomerDuplicateCheckResponse(BaseModel):
    severity: Literal["none", "suggestion", "warning", "blocking"]
    matches: list[CustomerDuplicateMatchResponse]


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


class TimeWindowResponse(BaseModel):
    """Echoes back the resolved [start, end) boundaries the KPI snapshot
    below was actually computed over -- so a client never has to
    reimplement app.analytics.time_windows' own date math just to know
    what "current_month" resolved to."""

    kind: str
    start: datetime
    end: datetime


class InvoiceCountsResponse(BaseModel):
    total: int
    pending: int
    paid: int
    overdue: int


class RevenueBreakdownResponse(BaseModel):
    """One currency's revenue, split by effective payment status -- see
    app.analytics.calculators.revenue.RevenueBreakdown. `paid` +
    `outstanding` always sum back to `total`."""

    currency_code: str
    total: Decimal
    paid: Decimal
    outstanding: Decimal
    overdue: Decimal


class CustomerRetentionResponse(BaseModel):
    total_invoiced_customers: int
    repeat_customers: int
    retention_rate_percent: float | None


class AveragePaymentTimeResponse(BaseModel):
    """`available=False` is an honest, documented gap, not an error --
    see app.analytics.calculators.payments for why this can't be computed
    yet (no paid_at timestamp exists on Invoice)."""

    available: bool
    average_days: float | None
    reason: str | None


class KpiSnapshotResponse(BaseModel):
    """A window-scoped snapshot of the core KPI-engine metrics --
    assembled by app.analytics.service.AnalyticsService from independently
    callable calculators, never computed inline by the router. See
    GET /organizations/{organization_id}/analytics/kpis."""

    window: TimeWindowResponse
    invoice_counts: InvoiceCountsResponse
    revenue_by_currency: dict[str, Decimal]
    revenue_breakdown: list[RevenueBreakdownResponse]
    average_invoice_value: dict[str, Decimal]
    customer_growth: int
    # Deliberately all-time, not window-scoped -- see
    # app.analytics.calculators.customers.get_customer_retention's own
    # docstring on why a lifetime relationship metric doesn't slice
    # meaningfully by an arbitrary window.
    customer_retention: CustomerRetentionResponse
    quote_acceptance_rate_percent: float | None
    average_payment_time: AveragePaymentTimeResponse


# --- Phase 16C: trend analysis & forecasting --------------------------


class PeriodComparisonResponse(BaseModel):
    """Mirrors app.analytics.comparison.PeriodComparison. `direction` is
    one of "up"/"down"/"flat"/"unknown" (see
    app.analytics.trend_direction.TrendDirection) -- exposed as a plain
    str here, the same convention TimeWindowResponse.kind already uses
    for its own enum-backed domain field."""

    current: Decimal
    previous: Decimal
    absolute_difference: Decimal
    percentage_difference: Decimal | None
    direction: str


class SeriesPointResponse(BaseModel):
    """Mirrors app.analytics.calculators.trends.SeriesPoint -- one
    generic evolution-series point. `period`'s format depends on the
    request's `granularity` ("2026-07" monthly, "2026-Q3" quarterly,
    "2026" yearly). `currency_code` is null for currency-agnostic series
    (invoice/customer/quote counts)."""

    period: str
    value: Decimal
    currency_code: str | None


class ForecastResponse(BaseModel):
    """Mirrors app.analytics.forecast.Forecast. `available=False` is an
    honest gap (not enough history), never a fabricated forecast_value --
    see that module's own docstring. `inputs`/`method`/`window_size` are
    exposed instead of a prose explanation so the frontend can build its
    own translated explanation from these structured values.

    `plan_restricted` (Phase 17B) distinguishes *why* available=False:
    true means the organization's plan doesn't include forecasting at
    all (app.billing.capabilities.can_use_forecasting) -- a different
    frontend message ("upgrade to unlock") than the ordinary "not enough
    history yet" case, which always has plan_restricted=False."""

    available: bool
    method: str | None
    forecast_value: Decimal | None
    inputs: list[Decimal]
    window_size: int | None
    reason: str | None
    plan_restricted: bool = False


class TrendSnapshotResponse(BaseModel):
    """Response from GET /organizations/{organization_id}/analytics/trends
    -- assembled entirely by AnalyticsService's trend/series/forecast
    methods, each delegating to app.analytics.calculators.trends /
    app.analytics.forecast. `comparison_kind` and `granularity` echo back
    the resolved request parameters, the same "tell the client what it
    actually got" convention KpiSnapshotResponse.window already follows."""

    comparison_kind: str
    granularity: str
    revenue_trend: dict[str, PeriodComparisonResponse]
    invoice_count_trend: PeriodComparisonResponse
    customer_growth_trend: PeriodComparisonResponse
    quote_count_trend: PeriodComparisonResponse
    revenue_series: list[SeriesPointResponse]
    invoice_count_series: list[SeriesPointResponse]
    customer_count_series: list[SeriesPointResponse]
    quote_conversion_series: list[SeriesPointResponse]
    revenue_forecast: dict[str, ForecastResponse]
    invoice_count_forecast: ForecastResponse


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
    # Set only when reason_code is a duplicate-against-the-database reason
    # (e.g. duplicate_email/duplicate_tax_id) -- None for an in-file-only
    # duplicate (the earlier occurrence is just another row, not yet a
    # real customer to link to) and for every non-duplicate row.
    duplicate_customer_id: str | None = None
    duplicate_customer_name: str | None = None


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
    duplicate_customer_id: str | None = None
    duplicate_customer_name: str | None = None


class ImportConfirmResponse(BaseModel):
    imported_count: int
    skipped_duplicate_count: int
    failed_count: int
    total_processed: int
    # Every row, never capped — this is the authoritative final record and
    # (client-side) error-report source, unlike preview_rows above.
    row_results: list[ImportConfirmRowResult]


# --- Platform administration (app.routers.platform_admin) ---
#
# Every field below traces to a real column or a documented derivation --
# see that router's module docstring for exactly which. Two fields in
# particular are NOT real stored timestamps: `created_at` on both the
# organization and user summaries/details is derived from the earliest
# active OrganizationMember row (organizations and their first owner
# membership are created together at registration, so this is a faithful
# proxy -- neither Organization nor User has its own created_at column
# today). There is deliberately no `status`/`suspended` field on
# organizations yet (Phase 13D adds it) and no `last_login_at` on users
# (never tracked anywhere in this app).


class PlatformSystemHealthResponse(BaseModel):
    database_reachable: bool
    email_provider_configured: bool
    email_provider: str | None
    ai_provider_configured: bool
    ai_provider: str | None
    reminder_emails_pending: int
    reminder_emails_sent_7d: int
    reminder_emails_failed_7d: int
    # Phase 21 additions -- see app.platform_metrics.health. Extends this
    # SAME response rather than a second health endpoint.
    queue_pending: int
    queue_running: int
    queue_retry_scheduled: int
    jobs_failed_total: int
    jobs_succeeded_total: int
    storage_used_mb: int
    database_size_mb: float | None
    average_api_latency_ms: float | None
    error_rate_percent: float | None
    request_sample_count: int


class PlatformBusinessMetricsResponse(BaseModel):
    """GET /admin/dashboard/business -- see app.platform_metrics.business
    for the single query this response is built from. `currency` is a
    single-currency-deployment simplification (see that module's own
    docstring); `average_revenue_per_organization` is MRR divided by
    paying_organizations, 0 when there are none."""

    organizations_total: int
    active_users_total: int
    paying_organizations: int
    trial_organizations: int
    mrr: Decimal
    arr: Decimal
    currency: str
    churn_rate_30d: float
    conversion_rate_30d: float
    average_revenue_per_organization: Decimal


class PlatformUsageMetricsResponse(BaseModel):
    """GET /admin/dashboard/usage -- see app.platform_metrics.usage.
    `api_keys_active`/`api_keys_used_7d` are the honest ceiling of what
    this app tracks for API keys (no per-request log exists -- see that
    module's own docstring); every other field is a genuine count over
    its own table."""

    ai_requests_30d: int
    api_keys_active: int
    api_keys_used_7d: int
    webhook_deliveries_30d: int
    webhook_deliveries_succeeded_30d: int
    webhook_deliveries_failed_30d: int
    background_jobs_30d: int
    background_jobs_succeeded_30d: int
    background_jobs_failed_30d: int
    emails_sent_30d: int
    notifications_created_30d: int


class PlatformDailySignupCount(BaseModel):
    day: date
    count: int


class PlatformWeeklyActiveOrganizationsCount(BaseModel):
    week_start: date
    count: int


class PlatformFeatureAdoption(BaseModel):
    feature: str
    adopted_paying_organizations: int
    adopted_percent: float


class PlatformGrowthMetricsResponse(BaseModel):
    """GET /admin/dashboard/growth -- see app.platform_metrics.growth.
    `daily_signups`/`weekly_active_organizations` only include buckets
    with at least one row (no zero-filled gaps) -- the frontend fills
    gaps for charting, since a missing day IS zero, not absent data."""

    daily_signups: list[PlatformDailySignupCount]
    weekly_active_organizations: list[PlatformWeeklyActiveOrganizationsCount]
    monthly_growth_percent: float
    feature_adoption: list[PlatformFeatureAdoption]


class PlatformSettingsResponse(BaseModel):
    """GET /admin/settings -- dynamic settings (persisted in the
    PlatformSettings singleton, editable via PATCH) plus infrastructure
    readiness (environment-derived, read-only, never a secret value --
    see app.models.PlatformSettings's own docstring for why infra config
    has no column in that table at all). ai_provider/email_provider are
    None when not configured, which already functions as the required
    "boolean/status," not a raw dump of the underlying credentials."""

    maintenance_mode: bool
    registrations_enabled: bool
    ai_enabled: bool
    emails_enabled: bool
    invoice_reminders_enabled: bool
    quote_reminders_enabled: bool
    default_language: str
    default_currency: str
    updated_at: datetime
    updated_by_email: str | None
    version: int

    ai_provider: str | None
    email_provider: str | None
    cors_allowed_origins: list[str]


class PlatformSettingsUpdateRequest(BaseModel):
    """Body for PATCH /admin/settings -- every setting field is optional
    (a genuine partial update), but `reason` is always required and at
    least one setting field must actually be provided; both are enforced
    below rather than left to the router, so an empty or reason-less
    request never reaches it. default_language/default_currency reuse
    the exact enums RegisterRequest already validates against
    (OrganizationLanguage/CurrencyCode) -- an unrecognized value fails
    closed with a plain 422, the same guarantee PlatformRoleActionRequest
    gets from reusing PlatformRole for platform_role.

    expected_version is required on every PATCH -- the optimistic-
    concurrency token the caller must have read from a prior GET (or a
    prior PATCH's own response). It is deliberately kept separate from
    the editable setting fields below (excluded from the diff the router
    computes) since it is never itself a persisted setting, only a
    precondition on the write."""

    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(gt=0)
    maintenance_mode: bool | None = None
    registrations_enabled: bool | None = None
    ai_enabled: bool | None = None
    emails_enabled: bool | None = None
    invoice_reminders_enabled: bool | None = None
    quote_reminders_enabled: bool | None = None
    default_language: OrganizationLanguage | None = None
    default_currency: CurrencyCode | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)

    @model_validator(mode="after")
    def _reject_empty_update(self) -> "PlatformSettingsUpdateRequest":
        setting_fields = (
            "maintenance_mode",
            "registrations_enabled",
            "ai_enabled",
            "emails_enabled",
            "invoice_reminders_enabled",
            "quote_reminders_enabled",
            "default_language",
            "default_currency",
        )
        if all(getattr(self, field) is None for field in setting_fields):
            raise ValueError("At least one setting field must be provided.")
        return self


class PublicConfigResponse(BaseModel):
    """GET /public/config -- the ONLY two values the unauthenticated
    login/register UI needs, and deliberately nothing else: never
    internal readiness, feature-provider configuration, or any
    admin-only setting."""

    maintenance_mode: bool
    registrations_enabled: bool


_PLAN_LIMIT_FIELD_NAMES = (
    "max_users",
    "max_customers",
    "max_products",
    "max_invoices_per_month",
    "max_quotes_per_month",
    "max_ai_actions_per_month",
    "storage_limit_mb",
    "max_api_keys",
    "max_webhooks",
    "max_whatsapp_users",
    "monthly_whatsapp_actions",
)
_PLAN_FEATURE_FIELD_NAMES = (
    "custom_branding_enabled",
    "api_access_enabled",
    "advanced_reports_enabled",
    "analytics_enabled",
    "forecasting_enabled",
    "ai_enabled",
    "background_jobs_enabled",
    "whatsapp_enabled",
    "voice_messages_enabled",
)


class PlanLimits(BaseModel):
    """NULL = unlimited, 0 = unavailable, positive integer = hard limit
    for every field here -- see app.models.Plan's own docstring. Shared
    by the platform admin plan response and the organization-facing
    entitlements response so both render "unlimited" the same way."""

    max_users: int | None
    max_customers: int | None
    max_products: int | None
    max_invoices_per_month: int | None
    max_quotes_per_month: int | None
    max_ai_actions_per_month: int | None
    storage_limit_mb: int | None
    max_api_keys: int | None
    max_webhooks: int | None
    max_whatsapp_users: int | None
    monthly_whatsapp_actions: int | None


class PlanFeatures(BaseModel):
    """Commercial entitlement only -- whether the plan is *supposed* to
    allow the capability, not whether it's actually wired up and
    enforced anywhere yet (enforcement is a later phase). The last four
    were added in Phase 17A alongside the billing/subscription domain;
    the last two (Phase 23) gate the experimental WhatsApp assistant."""

    custom_branding_enabled: bool
    api_access_enabled: bool
    advanced_reports_enabled: bool
    analytics_enabled: bool
    forecasting_enabled: bool
    ai_enabled: bool
    background_jobs_enabled: bool
    whatsapp_enabled: bool
    voice_messages_enabled: bool


class PlanResponse(BaseModel):
    """GET/POST/PATCH /admin/plans(/{id}) -- the full plan definition,
    including the optimistic-concurrency `version` every mutation must
    round-trip as expected_version (see PlanUpdateRequest).

    `code`/`name`/`sort_order`/`is_active` are this app's own immutable-
    internal-identifier / editable-display-name / display-order / active
    fields (see Phase 17A's own completion report for this exact
    mapping) -- `code` is never accepted by PlanUpdateRequest, which is
    what makes it immutable through the API, not a runtime check.
    `monthly_price`/`yearly_price` are null for "contact us" / custom
    pricing (the Enterprise seed row) -- informational only, no
    checkout/charging exists anywhere in this app."""

    id: str
    code: str
    name: str
    description: str | None
    is_active: bool
    is_default: bool
    sort_order: int
    public: bool
    monthly_price: Decimal | None
    yearly_price: Decimal | None
    currency: str
    limits: PlanLimits
    features: PlanFeatures
    version: int
    created_at: datetime
    updated_at: datetime


class PlansListResponse(BaseModel):
    """GET /admin/plans -- deliberately a plain list, no pagination
    wrapper: this app has exactly 4 built-in plans today and plans are
    never deleted, so the total count stays small by construction (see
    Plan's own docstring on why deletion isn't supported)."""

    items: list[PlanResponse]


def _validate_plan_code(value: str) -> str:
    value = value.strip()
    if not value or not all(c.islower() or c.isdigit() or c in "_-" for c in value):
        raise ValueError("code must be lowercase letters, digits, underscores, or hyphens only")
    return value


class PlanCreateRequest(BaseModel):
    """Body for POST /admin/plans. `code` is required and immutable
    forever after creation (see Plan's own docstring) -- PlanUpdateRequest
    below has no code field at all, which is what makes it impossible to
    change through the API, not a runtime check. `reason` is mandatory
    for consistency with every other platform-admin mutation in this
    app (suspend/reactivate, settings updates, user actions)."""

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int = 0
    public: bool = True
    monthly_price: Decimal | None = None
    yearly_price: Decimal | None = None
    currency: str = Field(default="USD", min_length=3, max_length=8)
    max_users: int | None = None
    max_customers: int | None = None
    max_products: int | None = None
    max_invoices_per_month: int | None = None
    max_quotes_per_month: int | None = None
    max_ai_actions_per_month: int | None = None
    storage_limit_mb: int | None = None
    max_api_keys: int | None = None
    max_webhooks: int | None = None
    max_whatsapp_users: int | None = None
    monthly_whatsapp_actions: int | None = None
    custom_branding_enabled: bool = False
    api_access_enabled: bool = False
    advanced_reports_enabled: bool = False
    analytics_enabled: bool = False
    forecasting_enabled: bool = False
    ai_enabled: bool = False
    background_jobs_enabled: bool = False
    whatsapp_enabled: bool = False
    voice_messages_enabled: bool = False
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("code")
    @classmethod
    def _code_valid(cls, value: str) -> str:
        return _validate_plan_code(value)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)

    @field_validator(*_PLAN_LIMIT_FIELD_NAMES)
    @classmethod
    def _limit_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("must be a non-negative integer, or null for unlimited")
        return value

    @field_validator("monthly_price", "yearly_price")
    @classmethod
    def _price_non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("must be a non-negative amount, or null for custom/contact-us pricing")
        return value


class PlanUpdateRequest(BaseModel):
    """Body for PATCH /admin/plans/{id} -- a genuine partial update
    (every field but reason/expected_version is optional), matching
    PlatformSettingsUpdateRequest's exact shape and exclude_unset
    contract. No `code` or `is_active`/`is_default` field exists here on
    purpose: code is immutable, and is_active/is_default only ever
    change through their own dedicated endpoints (activate/deactivate/
    make-default), which have their own audit actions and, for
    make-default, a second plan's row to update in the same
    transaction -- folding them into a generic PATCH would blur that."""

    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = None
    public: bool | None = None
    monthly_price: Decimal | None = None
    yearly_price: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    max_users: int | None = None
    max_customers: int | None = None
    max_products: int | None = None
    max_invoices_per_month: int | None = None
    max_quotes_per_month: int | None = None
    max_ai_actions_per_month: int | None = None
    storage_limit_mb: int | None = None
    max_api_keys: int | None = None
    max_webhooks: int | None = None
    max_whatsapp_users: int | None = None
    monthly_whatsapp_actions: int | None = None
    custom_branding_enabled: bool | None = None
    api_access_enabled: bool | None = None
    advanced_reports_enabled: bool | None = None
    analytics_enabled: bool | None = None
    forecasting_enabled: bool | None = None
    ai_enabled: bool | None = None
    background_jobs_enabled: bool | None = None
    whatsapp_enabled: bool | None = None
    voice_messages_enabled: bool | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)

    @field_validator(*_PLAN_LIMIT_FIELD_NAMES)
    @classmethod
    def _limit_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("must be a non-negative integer, or null for unlimited")
        return value

    @field_validator("monthly_price", "yearly_price")
    @classmethod
    def _price_non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("must be a non-negative amount, or null for custom/contact-us pricing")
        return value

    @model_validator(mode="after")
    def _reject_empty_update(self) -> "PlanUpdateRequest":
        # monthly_price/yearly_price are deliberately excluded from this
        # check: None is both "not being changed" (PATCH semantics) and a
        # perfectly valid target value (custom/contact-us pricing), so it
        # can never distinguish the two -- a caller who only wants to set
        # a plan's price to "custom" would otherwise be unable to combine
        # that with leaving every other field alone. public/currency are
        # unambiguous (no field here can legitimately be set to None) so
        # they stay in the check.
        editable_fields = (
            "name",
            "description",
            "sort_order",
            "public",
            "currency",
            *_PLAN_LIMIT_FIELD_NAMES,
            *_PLAN_FEATURE_FIELD_NAMES,
        )
        if all(getattr(self, field) is None for field in editable_fields):
            raise ValueError("At least one field must be provided.")
        return self


class PlanActionRequest(BaseModel):
    """Body for POST /admin/plans/{id}/activate|deactivate|make-default
    -- same optimistic-concurrency contract as PlanUpdateRequest (this
    plan's own version must match), plus the same mandatory-reason
    convention as every other platform-admin mutation."""

    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)


class OrganizationPlanChangeRequest(BaseModel):
    """Body for PATCH /admin/organizations/{id}/plan. `plan_id` must
    resolve to an active plan (see app.routers.platform_admin.
    update_organization_plan) -- inactive plans can never be newly
    assigned, only kept by an organization that was already on them
    before it was deactivated. Typed confirmation (matching the
    organization name) is enforced only on the frontend, same precedent
    as suspend/reactivate -- the API's own guarantee is just the
    mandatory, non-blank reason."""

    plan_id: str
    reason: str = Field(min_length=1, max_length=1000)
    # Optional, unlike Plan/PlatformSettings's mandatory expected_version --
    # this endpoint predates Phase P2.1's concurrency hardening and existing
    # callers never sent one, so it stays optional to preserve backward
    # compatibility (see docs/subscription_concurrency.md). When supplied,
    # the router performs an early staleness check for a friendlier 409
    # before ever calling BillingService; when omitted, the subscription's
    # version_id_col-backed protection (see app.models.Subscription's own
    # docstring) still makes a true lost update impossible either way.
    expected_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)


class OrganizationEntitlementsResponse(BaseModel):
    """GET /organizations/{id}/entitlements -- the tenant-facing,
    read-only view of what an organization's current plan allows. Never
    includes anything about other plans, pricing, or billing (out of
    scope for this phase) -- only this organization's own resolved
    entitlements, via app.services.entitlements."""

    plan_id: str
    plan_code: str
    plan_name: str
    limits: PlanLimits
    features: PlanFeatures


# --- Phase 17A: billing / subscription domain --------------------------
#
# Provider-independent throughout: no field here ever exposes a payment
# token, a provider credential, or anything charge-related -- see
# Subscription's own docstring in app.models for why provider_name/
# provider_reference exist (forward-compatibility only, always null
# today) and app.billing.service.BillingService for where every field
# below actually gets its value.


class CapabilitiesResponse(BaseModel):
    """The resolved capability layer (see app.billing.capabilities) for
    one organization -- feature flags plus remaining quotas, so the
    frontend never has to re-derive "can I create another X" from raw
    limits/usage itself."""

    can_use_ai: bool
    can_use_analytics: bool
    can_use_forecasting: bool
    can_use_background_jobs: bool
    can_create_invoice: bool
    can_create_quote: bool
    can_create_api_key: bool
    can_create_webhook: bool
    remaining_invoice_quota: int | None
    remaining_quote_quota: int | None
    remaining_users: int | None
    remaining_api_keys: int | None
    remaining_webhooks: int | None


class SubscriptionResponse(BaseModel):
    """GET /organizations/{organization_id}/subscription -- the tenant-
    facing, read-only view of an organization's own subscription.
    Deliberately does not include provider_name/provider_reference (see
    module note above) or any other organization's data."""

    id: str
    organization_id: str
    plan: PlanResponse
    status: str
    billing_period: str
    trial_start: datetime | None
    trial_end: datetime | None
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    canceled_at: datetime | None
    ended_at: datetime | None
    capabilities: CapabilitiesResponse
    created_at: datetime
    updated_at: datetime


class StartCheckoutRequest(BaseModel):
    """POST /organizations/{organization_id}/billing/checkout -- Phase 18's
    first tenant-initiated plan-change entry point (every prior phase's
    plan changes were platform-admin-only). `plan_id` is the target plan;
    `success_url`/`cancel_url` are where the provider's own hosted
    checkout page redirects back to once the tenant finishes (or
    abandons) the flow -- validated against nothing here beyond being
    non-empty strings, since the provider itself is what actually
    redirects the browser there."""

    plan_id: str
    billing_period: str
    success_url: str
    cancel_url: str


class StartCheckoutResponse(BaseModel):
    """The URL to redirect the tenant's browser to -- nothing about the
    organization's Subscription changes yet; that only happens once the
    provider's own checkout_completed webhook event arrives (see
    app.billing.service.BillingService.sync_from_webhook_event)."""

    checkout_url: str


class StartPortalSessionRequest(BaseModel):
    """POST /organizations/{organization_id}/billing/portal -- `return_url`
    is where the provider's own hosted billing-management page sends the
    browser back once the tenant is done."""

    return_url: str


class StartPortalSessionResponse(BaseModel):
    portal_url: str


class SubscriptionEventResponse(BaseModel):
    """One row of subscription HISTORY (see app.models.SubscriptionEvent's
    own docstring on why this is distinct from PlatformAuditLog).
    `previous_values`/`new_values`/`metadata` are already-parsed JSON
    objects here, never the raw encoded string the database stores."""

    id: str
    subscription_id: str
    organization_id: str
    actor_user_id: str | None
    event_type: str
    previous_values: dict | None
    new_values: dict | None
    metadata: dict | None
    created_at: datetime


class PaginatedSubscriptionEvents(BaseModel):
    total: int
    items: list[SubscriptionEventResponse]


class PlatformSubscriptionSummary(BaseModel):
    """One row of GET /admin/subscriptions -- deliberately narrower than
    the detail response (no event history), matching
    PlatformOrganizationSummary's own list-vs-detail precedent."""

    id: str
    organization_id: str
    organization_name: str
    plan_code: str
    plan_name: str
    status: str
    billing_period: str
    trial_end: datetime | None
    current_period_end: datetime
    cancel_at_period_end: bool
    created_at: datetime


class PaginatedPlatformSubscriptions(BaseModel):
    total: int
    items: list[PlatformSubscriptionSummary]


class PlatformSubscriptionDetail(BaseModel):
    """GET /admin/subscriptions/{id} -- the full subscription plus its
    own event history, for platform-admin inspection."""

    id: str
    organization_id: str
    organization_name: str
    plan: PlanResponse
    status: str
    billing_period: str
    trial_start: datetime | None
    trial_end: datetime | None
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    canceled_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
    events: list[SubscriptionEventResponse]


class AdminChangeSubscriptionPlanRequest(BaseModel):
    """Body for POST /admin/subscriptions/{id}/change-plan. Direction
    (upgrade vs. downgrade) is resolved server-side by comparing
    Plan.sort_order -- never supplied by the caller, since that's exactly
    the kind of plan-identity assumption this domain must never depend
    on (see app.billing.service.BillingService's own docstring)."""

    plan_id: str
    reason: str = Field(min_length=1, max_length=1000)
    # See OrganizationPlanChangeRequest's own comment on why this is
    # optional rather than mandatory like Plan/PlatformSettings.
    expected_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)


class AdminSubscriptionActionRequest(BaseModel):
    """Body for POST /admin/subscriptions/{id}/cancel|reactivate|resume."""

    reason: str = Field(min_length=1, max_length=1000)
    # See OrganizationPlanChangeRequest's own comment on why this is
    # optional rather than mandatory like Plan/PlatformSettings.
    expected_version: int | None = Field(default=None, gt=0)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)


class UsageResourceSnapshot(BaseModel):
    """used/limit/unlimited for exactly one plan-limited resource -- see
    app.services.organization_usage.ResourceUsage, which this mirrors
    field-for-field. The frontend renders "{used} / {limit}" or
    "Unlimited" directly; no percentage or warning threshold is computed
    here (Phase 14B measures usage only, it does not enforce or warn)."""

    used: int
    limit: int | None
    unlimited: bool


class OrganizationUsageResponse(BaseModel):
    """GET /organizations/{id}/usage -- the tenant-facing, read-only
    snapshot of how much of each plan-limited resource this organization
    is currently using, paired with that resource's entitled limit. Every
    value comes from app.services.organization_usage.get_usage_snapshot;
    this is a pure read with no audit row and no side effect."""

    users: UsageResourceSnapshot
    customers: UsageResourceSnapshot
    products: UsageResourceSnapshot
    invoices: UsageResourceSnapshot
    quotes: UsageResourceSnapshot
    ai_actions: UsageResourceSnapshot
    storage: UsageResourceSnapshot


class PlatformDashboardResponse(BaseModel):
    organizations_total: int
    organizations_new_7d: int
    organizations_new_30d: int
    users_total: int
    users_new_7d: int
    users_new_30d: int
    invoices_total: int
    quotes_total: int
    customers_total: int
    products_total: int
    reminder_emails_sent_7d: int
    reminder_emails_failed_7d: int
    ai_actions_executed_7d: int
    health: PlatformSystemHealthResponse


class PlatformOrganizationSummary(BaseModel):
    id: str
    name: str
    business_name: str | None
    status: OrganizationStatus
    owner_email: str | None
    members_count: int
    invoices_count: int
    quotes_count: int
    customers_count: int
    created_at: datetime | None
    last_activity_at: datetime | None


class PlatformOrganizationMember(BaseModel):
    user_id: str
    email: str
    role: str
    status: str
    joined_at: datetime


class PlatformOrganizationRecentDocument(BaseModel):
    type: Literal["invoice", "quote"]
    number: str
    status: str
    total: Decimal
    currency_code: str
    created_at: datetime


class PlatformOrganizationDetail(BaseModel):
    id: str
    name: str
    business_name: str | None
    status: OrganizationStatus
    owner_email: str | None
    members_count: int
    invoices_count: int
    quotes_count: int
    customers_count: int
    products_count: int
    language: str
    currency_code: str
    timezone: str
    plan_id: str
    plan_code: str
    plan_name: str
    usage: OrganizationUsageResponse
    created_at: datetime | None
    last_activity_at: datetime | None
    members: list[PlatformOrganizationMember]
    recent_documents: list[PlatformOrganizationRecentDocument]


class PaginatedPlatformOrganizationsResponse(BaseModel):
    total: int
    items: list[PlatformOrganizationSummary]


def _require_non_blank_reason(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("reason must not be empty")
    return stripped


class PlatformOrganizationActionRequest(BaseModel):
    """Body for POST /admin/organizations/{id}/suspend|reactivate. `reason`
    is mandatory and must be non-empty after stripping whitespace -- a
    string of only spaces is not a reason, and both actions are recorded
    verbatim in PlatformAuditLog.reason."""

    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)


class PlatformUserOrganization(BaseModel):
    organization_id: str
    organization_name: str
    role: str
    status: str


class PlatformUserSummary(BaseModel):
    id: str
    email: str
    email_verified: bool
    status: UserStatus
    platform_role: str | None
    organizations_count: int
    created_at: datetime | None


class PlatformUserDetail(BaseModel):
    id: str
    email: str
    email_verified: bool
    status: UserStatus
    platform_role: str | None
    created_at: datetime | None
    organizations: list[PlatformUserOrganization]


class PaginatedPlatformUsersResponse(BaseModel):
    total: int
    items: list[PlatformUserSummary]


class PlatformUserActionRequest(BaseModel):
    """Body for POST /admin/users/{id}/disable|enable. Same non-blank
    `reason` contract as PlatformOrganizationActionRequest."""

    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)


class PlatformRoleActionRequest(BaseModel):
    """Body for POST /admin/users/{id}/platform-role. `role` being
    PlatformRole | None (never a bare str) is what makes an unknown role
    value fail closed at the schema layer with a plain 422, before the
    request ever reaches the service layer -- None means "revoke,"
    "super_admin" is the only grantable value today (see
    app.platform_permissions.PlatformRole)."""

    role: PlatformRole | None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        return _require_non_blank_reason(value)


class PlatformUserActionResponse(BaseModel):
    """Generic success message for actions that don't return the full
    PlatformUserDetail shape (force-verify-email, send-password-reset) --
    deliberately never includes a token, hash, or other secret."""

    message: str


class PlatformAuditLogEntry(BaseModel):
    """One row, already sanitized before this schema ever sees it --
    `details` has been through app.platform_audit_sanitize.
    sanitize_audit_details and `client_ip` through mask_client_ip by the
    time the router builds this. target_type is derived (never a stored
    column) from which of target_organization_id/target_user_id is set;
    the *_name/*_email pair for whichever target type doesn't apply is
    normalized to None here, even though the underlying row stores ""
    for target_organization_name as its "not applicable" sentinel (see
    PlatformAuditLog's own docstring) -- API consumers should never have
    to know about that storage-level convention."""

    id: str
    action: str
    actor_user_id: str | None
    actor_email: str
    target_type: Literal["organization", "user"] | None
    target_organization_id: str | None
    target_organization_name: str | None
    target_user_id: str | None
    target_user_email: str | None
    reason: str
    details: dict[str, Any] | None
    client_ip: str | None
    created_at: datetime


class PaginatedPlatformAuditLogResponse(BaseModel):
    total: int
    items: list[PlatformAuditLogEntry]


class PlatformBackgroundJobEntry(BaseModel):
    """One BackgroundJob row for the Platform Admin Jobs view -- never
    includes `payload` (see PlatformBackgroundJobDetail below for the
    one place that does, gated behind the detail endpoint rather than
    the list, matching PlatformAuditLogEntry's own "list is a summary,
    detail has more" precedent). Every job type's payload is already
    documented as containing only IDs/validated data, never a secret
    (see BackgroundJob.payload's own docstring in app/models.py), so
    this isn't a security gate so much as keeping the list response
    small."""

    id: str
    organization_id: str | None
    job_type: str
    status: str
    queue: str
    priority: int
    attempts: int
    max_attempts: int
    available_at: datetime
    claimed_at: datetime | None
    claimed_by: str | None
    lease_expires_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    result_summary: str | None
    created_at: datetime
    updated_at: datetime


class PlatformBackgroundJobDetail(PlatformBackgroundJobEntry):
    payload: dict[str, Any]
    idempotency_key: str | None


class PaginatedPlatformBackgroundJobsResponse(BaseModel):
    total: int
    items: list[PlatformBackgroundJobEntry]


class PlatformJobActionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    permissions: list[ApiKeyPermission] = Field(min_length=1)
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    """Never includes the secret -- see OrganizationApiKey's own
    docstring. `status` is computed (app.api_key_status), not a stored
    column; `permissions` is decoded here from the row's JSON-encoded
    column into a real typed list, so API consumers never see the
    storage-level string representation."""

    id: str
    organization_id: str
    name: str
    description: str
    prefix: str
    permissions: list[ApiKeyPermission]
    status: ApiKeyStatus
    created_by: str | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    last_used_ip: str | None
    revoked_at: datetime | None
    revoked_by: str | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    """The one and only response shape that ever carries the complete,
    usable key -- returned exactly once, from the create and rotate
    endpoints. Never returned by GET/list; there is no "reveal" route."""

    api_key: str


# --- Webhooks (Phase 15B) --------------------------------------------------

_WEBHOOK_EVENT_VALUES = {e.value for e in WebhookEventType}
_WEBHOOK_WILDCARD = "*"


def _validate_subscribed_events(value: list[str]) -> list[str]:
    for item in value:
        if item != _WEBHOOK_WILDCARD and item not in _WEBHOOK_EVENT_VALUES:
            raise ValueError(f"Unknown webhook event type: {item}")
    return value


class WebhookEventCatalogEntry(BaseModel):
    """One row of the static, complete event catalog (GET
    /organizations/{id}/webhooks/event-types) -- the frontend's
    event-subscription selector groups by `domain` rather than
    hardcoding its own copy of app.webhook_event_type.WebhookEventType,
    so a new event type added there is picked up automatically."""

    event_type: str
    domain: str


class WebhookEndpointCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    description: str = Field(default="", max_length=500)
    # At least one selection is required -- an endpoint subscribed to
    # nothing would be silent, dead configuration; "*" is a valid single
    # entry meaning "every event type, including future ones" (see
    # app.services.webhook_endpoints._encode_events).
    subscribed_events: list[str] = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def _validate_url_scheme(cls, value: str) -> str:
        if not (value.startswith("https://") or value.startswith("http://")):
            raise ValueError("url must start with https:// (or http:// in local development)")
        return value

    @field_validator("subscribed_events")
    @classmethod
    def _validate_events(cls, value: list[str]) -> list[str]:
        return _validate_subscribed_events(value)


class WebhookEndpointUpdateRequest(BaseModel):
    """Partial update -- only fields explicitly set by the caller are
    applied (see app.services.webhook_endpoints.update_endpoint, which
    disambiguates "not given" from "given as empty" via the router's own
    `model_fields_set` check, the same _UNSET-sentinel problem
    app.services.quotes.update_quote_record solves)."""

    url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=500)
    subscribed_events: list[str] | None = Field(default=None, min_length=1)

    @field_validator("url")
    @classmethod
    def _validate_url_scheme(cls, value: str | None) -> str | None:
        if value is not None and not (value.startswith("https://") or value.startswith("http://")):
            raise ValueError("url must start with https:// (or http:// in local development)")
        return value

    @field_validator("subscribed_events")
    @classmethod
    def _validate_events(cls, value: list[str] | None) -> list[str] | None:
        return _validate_subscribed_events(value) if value is not None else None


class WebhookEndpointResponse(BaseModel):
    """Never includes `secret` -- see WebhookEndpoint's own docstring in
    app/models.py. `subscribed_events` is decoded here from the row's
    JSON-encoded column into a real typed list (which may be exactly
    `["*"]`), matching ApiKeyResponse's own decode-at-the-boundary
    convention."""

    id: str
    organization_id: str
    url: str
    description: str
    subscribed_events: list[str]
    enabled: bool
    active: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    last_rotated_at: datetime | None


class WebhookEndpointCreatedResponse(WebhookEndpointResponse):
    """The one and only response shape that ever carries the complete
    signing secret -- returned exactly once, from the create and
    rotate-secret endpoints. Never returned by GET/list."""

    secret: str


class WebhookEventResponse(BaseModel):
    id: str
    organization_id: str
    event_type: str
    object_type: str
    object_id: str
    payload: dict[str, Any]
    created_at: datetime


class WebhookDeliveryResponse(BaseModel):
    id: str
    organization_id: str
    event_id: str
    endpoint_id: str
    status: WebhookDeliveryStatus
    trigger: WebhookDeliveryTrigger
    attempt_number: int
    request_url: str
    response_status_code: int | None
    response_body_snippet: str | None
    error_message: str | None
    duration_ms: int | None
    attempted_at: datetime | None
    next_retry_at: datetime | None
    created_at: datetime


class PaginatedWebhookDeliveriesResponse(BaseModel):
    total: int
    items: list[WebhookDeliveryResponse]


class WebhookDeliveryDetailResponse(WebhookDeliveryResponse):
    """Adds the signed request headers (safe to show -- see
    app.services.webhook_deliveries._headers_for_storage's own docstring:
    it's a computed signature, never the secret itself) and the full
    triggering event, so the delivery-detail view can show payload +
    response side by side without a second request."""

    request_headers: dict[str, str] | None
    event: WebhookEventResponse


class NotificationResponse(BaseModel):
    """One in-app Notification row addressed to the current user (see
    app.models.Notification) -- title/body are already the frozen,
    rendered text (see app.notifications.copy), never a raw payload the
    frontend would have to format itself."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    title: str
    body: str
    object_type: str
    object_id: str
    read_at: datetime | None
    created_at: datetime


class PaginatedNotificationsResponse(BaseModel):
    total: int
    unread_count: int
    items: list[NotificationResponse]


class AuditEntryResponse(BaseModel):
    """One immutable row from the tenant-facing audit timeline (see
    app.models.AuditEntry, Phase 22) -- actor_email is resolved live
    against the current Users table for display (AuditEntry itself keeps
    only actor_user_id, mirroring WebhookAuditLog's simpler precedent
    rather than PlatformAuditLog's own actor_email snapshot), and is None
    both when there was no human actor and when the actor's account has
    since been deleted."""

    id: str
    organization_id: str
    actor_user_id: str | None
    actor_email: str | None
    event_type: str
    resource_type: str
    resource_id: str
    metadata: dict[str, Any] | None
    created_at: datetime


class PaginatedAuditEntriesResponse(BaseModel):
    total: int
    items: list[AuditEntryResponse]


class NotificationPreferenceResponse(BaseModel):
    """Reflects app.notifications.service.is_email_enabled's own
    default-True-when-no-row-exists semantics -- this response always has
    a value, even for a user who has never touched their preferences."""

    email_enabled: bool


class UpdateNotificationPreferenceRequest(BaseModel):
    email_enabled: bool
