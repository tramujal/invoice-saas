from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.invoice_numbering import format_invoice_number
from app.payment_status import PaymentStatus


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


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=72)
    organization_name: str = Field(min_length=1, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    currency_code: str


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


class CustomerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    phone: str = Field(default="", max_length=64)
    address: str = Field(default="", max_length=512)


class CustomerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=512)


class DashboardResponse(BaseModel):
    total_revenue: Decimal
    total_invoices: int
    total_customers: int
    pending_invoices: int
    paid_invoices: int
    overdue_invoices: int
    revenue_this_month: Decimal
    revenue_last_month: Decimal
    revenue_growth_percent: Decimal | None
    recent_invoices: list[InvoiceSummaryResponse]


class MonthlySummaryPoint(BaseModel):
    month: str
    revenue: Decimal
    invoice_count: int


class PaymentStatusCountPoint(BaseModel):
    status: PaymentStatus
    count: int


class TopCustomerRevenue(BaseModel):
    customer_id: str
    customer_name: str
    revenue: Decimal


class DashboardAnalyticsResponse(BaseModel):
    monthly_summary: list[MonthlySummaryPoint]
    invoice_count_by_status: list[PaymentStatusCountPoint]
    top_customers: list[TopCustomerRevenue]


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    email: str
    phone: str
    address: str
    created_at: datetime
    updated_at: datetime
