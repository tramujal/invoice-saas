"""The three v1 AI assistant actions: create an invoice draft, update an
invoice's payment status, and send an existing invoice by email.

Every tool here resolves free-text references (customer_name,
invoice_reference) strictly within `organization_id`, never guesses an
ambiguous match, and delegates all actual reads/writes to
app.services.invoices -- the exact same functions app.routers.invoices
uses -- so there is exactly one implementation of "what a valid invoice
create/status-update/send-email looks like," never a second one that
could silently drift from the real endpoints' behavior.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.limits import AI_MAX_LINE_ITEMS
from app.ai.tools.base import ActionTool
from app.ai.tools.types import (
    ActionToolError,
    AmbiguousCustomerError,
    CustomerEmailMissingError,
    CustomerNotFoundError,
    ExecutionResult,
    InvoiceAlreadyPaidError,
    InvoiceDueDateMissingError,
    InvoiceNotFoundError,
    ProposalResult,
    ReminderAlreadySentError,
    RemindersDisabledError,
)
from app.currency import format_amount, get_currency_code, resolve_default_currency_code
from app.invoice_numbering import format_invoice_number
from app.models import Customer, Organization, User
from app.org_time import get_organization_today
from app.payment_status import PaymentStatus
from app.schemas import CurrencyCode, InvoiceLineItemCreate
from app.services.invoices import (
    CustomerEmailMissingError as ServiceCustomerEmailMissingError,
)
from app.services.invoices import (
    CustomerNotFoundInOrgError as ServiceCustomerNotFoundInOrgError,
)
from app.services.invoices import (
    EmailSendFailedError as ServiceEmailSendFailedError,
)
from app.services.invoices import (
    InvoiceAlreadyPaidError as ServiceInvoiceAlreadyPaidError,
)
from app.services.invoices import (
    InvoiceDueDateMissingError as ServiceInvoiceDueDateMissingError,
)
from app.services.invoices import (
    InvoiceNotFoundError as ServiceInvoiceNotFoundError,
)
from app.services.invoices import (
    ReminderAlreadySentError as ServiceReminderAlreadySentError,
)
from app.services.invoices import (
    ReminderSendFailedError as ServiceReminderSendFailedError,
)
from app.services.invoices import (
    RemindersDisabledError as ServiceRemindersDisabledError,
)
from app.services.invoices import (
    compute_invoice_totals,
    create_invoice_record,
    get_customer_in_org,
    get_invoice_in_org,
    send_invoice_email_record,
    send_manual_invoice_reminder,
    update_invoice_payment_status_record,
)

_MAX_CUSTOMER_MATCHES_TO_INSPECT = 20


def _resolve_customer_by_name(db: Session, organization_id: str, customer_name: str) -> Customer:
    """Case-insensitive substring match, scoped to this organization only
    -- same query shape as the existing customer search endpoint
    (app/routers/customers.py). 0 matches -> CustomerNotFoundError; 2+ ->
    AmbiguousCustomerError (never guessed); exactly 1 -> resolved."""
    term = customer_name.strip()
    if not term:
        raise CustomerNotFoundError(customer_name)

    matches = list(
        db.scalars(
            select(Customer)
            .where(
                Customer.organization_id == organization_id,
                Customer.name.ilike(f"%{term}%"),
            )
            .order_by(Customer.name.asc())
            .limit(_MAX_CUSTOMER_MATCHES_TO_INSPECT)
        ).all()
    )
    if not matches:
        raise CustomerNotFoundError(customer_name)
    if len(matches) > 1:
        raise AmbiguousCustomerError([c.name for c in matches])
    return matches[0]


def _resolve_invoice(db: Session, organization_id: str, invoice_reference: str):
    try:
        return get_invoice_in_org(db, organization_id, invoice_reference)
    except ServiceInvoiceNotFoundError:
        raise InvoiceNotFoundError(invoice_reference)


# --- create_invoice_draft ---------------------------------------------------


class CreateInvoiceDraftInput(BaseModel):
    """What the model calls the tool with. No customer_id/invoice_id field
    exists anywhere in this schema -- the model has no way to inject a raw
    id; only a free-text name it does not control the resolution of."""

    customer_name: str = Field(
        min_length=1,
        max_length=255,
        description="The customer's name, or a distinctive part of it, exactly as known to this business.",
    )
    line_items: list[InvoiceLineItemCreate] = Field(min_length=1, max_length=AI_MAX_LINE_ITEMS)
    tax_rate: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=1,
        description="Tax rate as a fraction, e.g. 0.1 for 10%.",
    )
    currency_code: CurrencyCode | None = Field(
        default=None,
        description="ISO currency code. Omit to use the organization's default currency.",
    )


class CreateInvoiceDraftResolved(BaseModel):
    """What's persisted in AssistantAction.input_payload and re-validated
    at confirm time -- customer_name has already been resolved to a real
    customer_id and is never looked up by name again."""

    customer_id: str
    line_items: list[InvoiceLineItemCreate]
    tax_rate: Decimal = Field(ge=0, le=1)
    currency_code: CurrencyCode | None = None


class CreateInvoiceDraftTool(ActionTool):
    name = "create_invoice_draft"
    description = (
        "Propose creating a new invoice draft for a customer in this organization. "
        "Resolves the customer by name within this organization only. Nothing is "
        "created until the user explicitly confirms the proposal."
    )
    input_schema = CreateInvoiceDraftInput
    resolved_schema = CreateInvoiceDraftResolved

    def build_proposal(
        self, db: Session, organization_id: str, current_user: User, raw_input: dict[str, Any]
    ) -> ProposalResult:
        data = CreateInvoiceDraftInput.model_validate(raw_input)
        customer = _resolve_customer_by_name(db, organization_id, data.customer_name)

        # Preview totals only -- never a DB write, never consumes the
        # invoice-number sequence. execute() recomputes these again from
        # the same resolved line items; this preview is never trusted as
        # authoritative.
        totals = compute_invoice_totals(data.line_items, data.tax_rate)

        organization = db.get(Organization, organization_id)
        currency_code = (
            data.currency_code.value
            if data.currency_code
            else resolve_default_currency_code(customer, organization)
        )

        resolved = CreateInvoiceDraftResolved(
            customer_id=customer.id,
            line_items=data.line_items,
            tax_rate=data.tax_rate,
            currency_code=data.currency_code,
        )

        summary = {
            "customer_name": customer.name,
            "currency_code": currency_code,
            "line_items": [
                {
                    "description": line.description,
                    "quantity": str(line.quantity),
                    "unit_price": str(line.unit_price),
                    "line_total": str(line_total),
                }
                for line, line_total in zip(data.line_items, totals.line_totals)
            ],
            "tax_rate": str(data.tax_rate),
            "subtotal": str(totals.subtotal),
            "tax_amount": str(totals.tax_amount),
            "total": str(totals.total),
        }
        return ProposalResult(
            resolved_input=resolved.model_dump(mode="json"), summary=summary
        )

    def execute(
        self, db: Session, organization_id: str, current_user: User, resolved: BaseModel
    ) -> ExecutionResult:
        assert isinstance(resolved, CreateInvoiceDraftResolved)
        try:
            customer = get_customer_in_org(db, organization_id, resolved.customer_id)
        except ServiceCustomerNotFoundInOrgError:
            raise CustomerNotFoundError(resolved.customer_id)

        invoice = create_invoice_record(
            db,
            organization_id,
            current_user,
            customer,
            resolved.currency_code,
            resolved.line_items,
            resolved.tax_rate,
        )
        return ExecutionResult(
            summary={
                "invoice_number": format_invoice_number(invoice.invoice_number),
                "currency_code": invoice.currency_code,
                "total": str(invoice.total),
            }
        )


# --- update_invoice_status --------------------------------------------------


class UpdateInvoiceStatusInput(BaseModel):
    invoice_reference: str = Field(
        min_length=1,
        max_length=32,
        description='The invoice number as shown to the user, e.g. "INV-000023", or its raw id.',
    )
    new_status: PaymentStatus


class UpdateInvoiceStatusResolved(BaseModel):
    invoice_id: str
    new_status: PaymentStatus


class UpdateInvoiceStatusTool(ActionTool):
    name = "update_invoice_status"
    description = (
        "Propose changing an existing invoice's payment status within this "
        "organization. Nothing changes until the user explicitly confirms."
    )
    input_schema = UpdateInvoiceStatusInput
    resolved_schema = UpdateInvoiceStatusResolved

    def build_proposal(
        self, db: Session, organization_id: str, current_user: User, raw_input: dict[str, Any]
    ) -> ProposalResult:
        data = UpdateInvoiceStatusInput.model_validate(raw_input)
        invoice = _resolve_invoice(db, organization_id, data.invoice_reference)

        resolved = UpdateInvoiceStatusResolved(invoice_id=invoice.id, new_status=data.new_status)
        summary = {
            "invoice_number": format_invoice_number(invoice.invoice_number),
            "old_status": invoice.payment_status,
            "new_status": data.new_status.value,
        }
        return ProposalResult(resolved_input=resolved.model_dump(mode="json"), summary=summary)

    def execute(
        self, db: Session, organization_id: str, current_user: User, resolved: BaseModel
    ) -> ExecutionResult:
        assert isinstance(resolved, UpdateInvoiceStatusResolved)
        try:
            invoice = get_invoice_in_org(db, organization_id, resolved.invoice_id)
        except ServiceInvoiceNotFoundError:
            raise InvoiceNotFoundError(resolved.invoice_id)

        invoice = update_invoice_payment_status_record(db, invoice, resolved.new_status)
        return ExecutionResult(
            summary={
                "invoice_number": format_invoice_number(invoice.invoice_number),
                "new_status": invoice.payment_status,
            }
        )


# --- send_invoice_email ------------------------------------------------------


class SendInvoiceEmailInput(BaseModel):
    invoice_reference: str = Field(
        min_length=1,
        max_length=32,
        description='The invoice number as shown to the user, e.g. "INV-000023", or its raw id.',
    )


class SendInvoiceEmailResolved(BaseModel):
    invoice_id: str


class SendInvoiceEmailTool(ActionTool):
    name = "send_invoice_email"
    description = (
        "Propose (re)sending an existing invoice to its customer by email. "
        "The recipient is always the email already on file for that invoice's "
        "customer -- there is no way to choose a different recipient. Nothing "
        "is sent until the user explicitly confirms."
    )
    input_schema = SendInvoiceEmailInput
    resolved_schema = SendInvoiceEmailResolved

    def build_proposal(
        self, db: Session, organization_id: str, current_user: User, raw_input: dict[str, Any]
    ) -> ProposalResult:
        data = SendInvoiceEmailInput.model_validate(raw_input)
        invoice = _resolve_invoice(db, organization_id, data.invoice_reference)

        customer = invoice.customer
        if customer is None or not customer.email:
            raise CustomerEmailMissingError(invoice.id)

        resolved = SendInvoiceEmailResolved(invoice_id=invoice.id)
        summary = {
            "invoice_number": format_invoice_number(invoice.invoice_number),
            "recipient_email": customer.email,
        }
        return ProposalResult(resolved_input=resolved.model_dump(mode="json"), summary=summary)

    def execute(
        self, db: Session, organization_id: str, current_user: User, resolved: BaseModel
    ) -> ExecutionResult:
        assert isinstance(resolved, SendInvoiceEmailResolved)
        try:
            invoice = get_invoice_in_org(db, organization_id, resolved.invoice_id)
        except ServiceInvoiceNotFoundError:
            raise InvoiceNotFoundError(resolved.invoice_id)

        try:
            result = send_invoice_email_record(db, invoice)
        except ServiceCustomerEmailMissingError:
            raise CustomerEmailMissingError(resolved.invoice_id)
        except ServiceEmailSendFailedError as exc:
            raise ActionToolError("Failed to send invoice email.") from exc

        return ExecutionResult(
            summary={
                "invoice_number": format_invoice_number(invoice.invoice_number),
                "recipient_email": result.sent_to,
            }
        )


# --- send_payment_reminder ---------------------------------------------------


class SendPaymentReminderInput(BaseModel):
    invoice_reference: str = Field(
        min_length=1,
        max_length=32,
        description='The invoice number as shown to the user, e.g. "INV-000023", or its raw id.',
    )


class SendPaymentReminderResolved(BaseModel):
    invoice_id: str


class SendPaymentReminderTool(ActionTool):
    name = "send_payment_reminder"
    description = (
        "Propose sending a payment reminder email for an existing, unpaid invoice "
        "that has a due date on file, to its customer. The recipient is always the "
        "email already on file for that invoice's customer -- there is no way to "
        "choose a different recipient. Shares the same one-per-day limit as the "
        "'Send reminder' button; nothing is sent until the user explicitly confirms."
    )
    input_schema = SendPaymentReminderInput
    resolved_schema = SendPaymentReminderResolved

    def build_proposal(
        self, db: Session, organization_id: str, current_user: User, raw_input: dict[str, Any]
    ) -> ProposalResult:
        data = SendPaymentReminderInput.model_validate(raw_input)
        invoice = _resolve_invoice(db, organization_id, data.invoice_reference)

        organization = db.get(Organization, organization_id)
        if organization is None or not organization.reminders_enabled:
            raise RemindersDisabledError(organization_id)

        if invoice.effective_payment_status == PaymentStatus.paid:
            raise InvoiceAlreadyPaidError(invoice.id)

        if invoice.due_date is None:
            raise InvoiceDueDateMissingError(invoice.id)

        customer = invoice.customer
        if customer is None or not customer.email:
            raise CustomerEmailMissingError(invoice.id)

        today_local = get_organization_today(organization)
        days_from_due = (invoice.due_date - today_local).days
        currency_code = get_currency_code(invoice)

        resolved = SendPaymentReminderResolved(invoice_id=invoice.id)
        summary = {
            "invoice_number": format_invoice_number(invoice.invoice_number),
            "customer_name": customer.name,
            "recipient_email": customer.email,
            "due_date": invoice.due_date.isoformat(),
            "days_until_due": days_from_due if days_from_due >= 0 else None,
            "days_overdue": -days_from_due if days_from_due < 0 else None,
            "total": format_amount(invoice.total, currency_code),
        }
        return ProposalResult(resolved_input=resolved.model_dump(mode="json"), summary=summary)

    def execute(
        self, db: Session, organization_id: str, current_user: User, resolved: BaseModel
    ) -> ExecutionResult:
        assert isinstance(resolved, SendPaymentReminderResolved)
        try:
            invoice = get_invoice_in_org(db, organization_id, resolved.invoice_id)
        except ServiceInvoiceNotFoundError:
            raise InvoiceNotFoundError(resolved.invoice_id)

        try:
            result = send_manual_invoice_reminder(
                db, organization_id, invoice, triggered_by="assistant"
            )
        except ServiceRemindersDisabledError:
            raise RemindersDisabledError(organization_id)
        except ServiceInvoiceAlreadyPaidError:
            raise InvoiceAlreadyPaidError(resolved.invoice_id)
        except ServiceInvoiceDueDateMissingError:
            raise InvoiceDueDateMissingError(resolved.invoice_id)
        except ServiceCustomerEmailMissingError:
            raise CustomerEmailMissingError(resolved.invoice_id)
        except ServiceReminderAlreadySentError:
            raise ReminderAlreadySentError(resolved.invoice_id)
        except ServiceReminderSendFailedError as exc:
            raise ActionToolError("Failed to send payment reminder.") from exc

        return ExecutionResult(
            summary={
                "invoice_number": format_invoice_number(invoice.invoice_number),
                "recipient_email": result.sent_to,
            }
        )
