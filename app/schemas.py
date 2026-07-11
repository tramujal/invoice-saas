from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.limits import (
    AI_MAX_HISTORY_MESSAGE_LENGTH,
    AI_MAX_HISTORY_MESSAGES,
    AI_MAX_HISTORY_TOTAL_CHARS,
    AI_MAX_USER_MESSAGE_LENGTH,
)
from app.customer_validation import is_valid_email_format
from app.invoice_numbering import format_invoice_number
from app.payment_status import PaymentStatus
from app.security import PASSWORD_POLICY_MESSAGE, password_meets_policy


class SortDirection(str, Enum):
    asc = "asc"
    desc = "desc"


class InvoiceSortField(str, Enum):
    invoice_number = "invoice_number"
    created_at = "created_at"
    total = "total"
    customer_name = "customer_name"


class CustomerSortField(str, Enum):
    name = "name"
    email = "email"
    created_at = "created_at"


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

    @field_validator(
        "business_name", "tax_id", "address", "phone", "email", "logo_url",
        mode="before",
    )
    @classmethod
    def _normalize_blank(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class InvoiceLineItemCreate(BaseModel):
    description: str = Field(min_length=1, max_length=512)
    quantity: Decimal = Field(gt=0, decimal_places=4, max_digits=14)
    unit_price: Decimal = Field(ge=0, decimal_places=2, max_digits=14)


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


class InvoiceLineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


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
    currency_code: str
    language: str
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
    currency_code: str
    language: str
    created_at: datetime

    @field_validator("invoice_number", mode="before")
    @classmethod
    def _format_number(cls, value: int | str) -> str:
        return _format_invoice_number(value)


class InvoicePaymentStatusUpdate(BaseModel):
    payment_status: PaymentStatus


class SendInvoiceEmailResponse(BaseModel):
    sent: bool
    sent_to: str


class PaginatedInvoicesResponse(BaseModel):
    """Total number of invoices matching the org filter (all pages), plus one page of rows."""

    total: int
    items: list[InvoiceSummaryResponse]


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


class DashboardAnalyticsResponse(BaseModel):
    monthly_summary: list[MonthlySummaryPoint]
    monthly_revenue_by_currency: list[MonthlyRevenuePoint]
    invoice_count_by_status: list[PaymentStatusCountPoint]
    # Top customers computed independently within each currency (a
    # customer can be "top" in USD and unranked in UYU) — entries are
    # tagged with currency_code so the frontend can filter to one
    # currency at a time without ever summing revenue across currencies.
    top_customers: list[TopCustomerRevenue]


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
