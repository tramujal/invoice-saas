from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.payment_status import PaymentStatus


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("Invalid email address")
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


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    organizations: list[OrganizationSummary]


class MeResponse(BaseModel):
    user: UserResponse
    organizations: list[OrganizationSummary]


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
    organization_id: str
    created_by_user_id: str | None
    customer_id: str | None
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    payment_status: PaymentStatus
    line_items: list[InvoiceLineItemResponse]


class InvoiceSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_id: str | None
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    payment_status: PaymentStatus
    created_at: datetime


class InvoicePaymentStatusUpdate(BaseModel):
    payment_status: PaymentStatus


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
