"""The three v1 AI assistant quote actions: create a quote draft, convert
an accepted quote into an invoice, and send an existing quote by email.

Mirrors app/ai/tools/invoices.py's exact rationale: every tool here
resolves free-text references (customer_name, quote_reference) strictly
within `organization_id`, never guesses an ambiguous match, and delegates
all actual reads/writes to app.services.quotes -- the same functions
app.routers.quotes uses -- so there is exactly one implementation of
"what a valid quote create/convert/send-email looks like."
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.limits import AI_MAX_LINE_ITEMS
from app.ai.tools.base import ActionTool
from app.ai.tools.invoices import AiInvoiceLineItemInput, _resolve_customer_by_name
from app.ai.tools.products import resolve_product_by_name
from app.ai.tools.types import (
    ActionToolError,
    CurrencyRequiredError,
    CustomerNotFoundError,
    ExecutionResult,
    LineItemIncompleteError,
    ProductCurrencyMismatchError,
    ProposalResult,
    QuoteAlreadyConvertedError,
    QuoteCustomerEmailMissingError,
    QuoteNotAcceptedError,
    QuoteNotFoundError,
)
from app.currency import CurrencyRequiredError as ServiceCurrencyRequiredError
from app.currency import ProductCurrencyMismatchError as ServiceProductCurrencyMismatchError
from app.currency import resolve_document_currency_code
from app.models import Customer, Product, User
from app.quote_numbering import format_quote_number
from app.schemas import CurrencyCode, QuoteLineItemCreate
from app.services.invoices import compute_invoice_totals
from app.services.quotes import (
    CustomerNotFoundInOrgError as ServiceCustomerNotFoundInOrgError,
)
from app.services.quotes import (
    EmailSendFailedError as ServiceEmailSendFailedError,
)
from app.services.quotes import (
    QuoteAlreadyConvertedError as ServiceQuoteAlreadyConvertedError,
)
from app.services.quotes import (
    QuoteNotAcceptedError as ServiceQuoteNotAcceptedError,
)
from app.services.quotes import (
    QuoteNotFoundError as ServiceQuoteNotFoundError,
)
from app.services.quotes import (
    CustomerEmailMissingError as ServiceCustomerEmailMissingError,
)
from app.services.quotes import (
    convert_quote_to_invoice,
    create_quote_record,
    get_customer_in_org,
    get_quote_in_org,
    send_quote_record,
)


def _resolve_quote(db: Session, organization_id: str, quote_reference: str):
    try:
        return get_quote_in_org(db, organization_id, quote_reference)
    except ServiceQuoteNotFoundError:
        raise QuoteNotFoundError(quote_reference)


def _resolve_quote_line_items(
    db: Session, organization_id: str, lines: list[AiInvoiceLineItemInput]
) -> tuple[list[QuoteLineItemCreate], dict[str, Product]]:
    """Same resolution logic as app.ai.tools.invoices._resolve_line_items,
    just producing QuoteLineItemCreate objects instead of
    InvoiceLineItemCreate -- reuses AiInvoiceLineItemInput (the model's
    input shape) and resolve_product_by_name (product resolution)
    unchanged, since neither is invoice-specific. Also returns every
    resolved Product keyed by id, for resolve_document_currency_code."""
    resolved: list[QuoteLineItemCreate] = []
    resolved_products_by_id: dict[str, Product] = {}
    for line in lines:
        if line.product_name:
            product = resolve_product_by_name(db, organization_id, line.product_name)
            resolved_products_by_id[product.id] = product
            description = line.description or product.name
            unit_price = (
                line.unit_price if line.unit_price is not None else product.default_unit_price
            )
            resolved.append(
                QuoteLineItemCreate(
                    description=description,
                    quantity=line.quantity,
                    unit_price=unit_price,
                    product_id=product.id,
                )
            )
        else:
            if line.description is None or line.unit_price is None:
                raise LineItemIncompleteError(
                    "Each line needs either a product name, or both a description and unit price."
                )
            resolved.append(
                QuoteLineItemCreate(
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    product_id=None,
                )
            )
    return resolved, resolved_products_by_id


# --- create_quote_draft ------------------------------------------------------


class CreateQuoteDraftInput(BaseModel):
    customer_name: str = Field(
        min_length=1,
        max_length=255,
        description="The customer's name, or a distinctive part of it, exactly as known to this business.",
    )
    line_items: list[AiInvoiceLineItemInput] = Field(min_length=1, max_length=AI_MAX_LINE_ITEMS)
    tax_rate: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=1,
        description="Tax rate as a fraction, e.g. 0.1 for 10%.",
    )
    currency_code: CurrencyCode | None = Field(
        default=None,
        description=(
            "ISO currency code. Omit when every line item resolves to a catalog "
            "product -- currency is inferred automatically from the first product's "
            "own currency. Required when any line item is a manual (non-catalog) line, "
            "since a manual line has no currency of its own to infer from."
        ),
    )


class CreateQuoteDraftResolved(BaseModel):
    customer_id: str
    line_items: list[QuoteLineItemCreate]
    tax_rate: Decimal = Field(ge=0, le=1)
    currency_code: CurrencyCode | None = None


class CreateQuoteDraftTool(ActionTool):
    name = "create_quote_draft"
    description = (
        "Propose creating a new quote (estimate) draft for a customer in this "
        "organization. Resolves the customer by name within this organization "
        "only. Nothing is created until the user explicitly confirms the proposal."
    )
    input_schema = CreateQuoteDraftInput
    resolved_schema = CreateQuoteDraftResolved

    def build_proposal(
        self, db: Session, organization_id: str, current_user: User, raw_input: dict[str, Any]
    ) -> ProposalResult:
        data = CreateQuoteDraftInput.model_validate(raw_input)
        customer = _resolve_customer_by_name(db, organization_id, data.customer_name)
        resolved_line_items, resolved_products_by_id = _resolve_quote_line_items(
            db, organization_id, data.line_items
        )

        totals = compute_invoice_totals(resolved_line_items, data.tax_rate)  # type: ignore[arg-type]

        try:
            currency_code = resolve_document_currency_code(
                data.currency_code.value if data.currency_code else None,
                resolved_line_items,
                resolved_products_by_id,
            )
        except ServiceCurrencyRequiredError:
            raise CurrencyRequiredError()
        except ServiceProductCurrencyMismatchError as exc:
            raise ProductCurrencyMismatchError(
                exc.product_name, exc.product_currency, exc.document_currency
            )

        resolved = CreateQuoteDraftResolved(
            customer_id=customer.id,
            line_items=resolved_line_items,
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
                for line, line_total in zip(resolved_line_items, totals.line_totals)
            ],
            "tax_rate": str(data.tax_rate),
            "subtotal": str(totals.subtotal),
            "tax_amount": str(totals.tax_amount),
            "total": str(totals.total),
        }
        return ProposalResult(resolved_input=resolved.model_dump(mode="json"), summary=summary)

    def execute(
        self, db: Session, organization_id: str, current_user: User, resolved: BaseModel
    ) -> ExecutionResult:
        assert isinstance(resolved, CreateQuoteDraftResolved)
        try:
            customer = get_customer_in_org(db, organization_id, resolved.customer_id)
        except ServiceCustomerNotFoundInOrgError:
            raise CustomerNotFoundError(resolved.customer_id)

        try:
            quote = create_quote_record(
                db,
                organization_id,
                current_user,
                customer,
                resolved.currency_code,
                resolved.line_items,
                resolved.tax_rate,
            )
        except ServiceCurrencyRequiredError:
            raise CurrencyRequiredError()
        except ServiceProductCurrencyMismatchError as exc:
            raise ProductCurrencyMismatchError(
                exc.product_name, exc.product_currency, exc.document_currency
            )
        return ExecutionResult(
            summary={
                "quote_number": format_quote_number(quote.quote_number),
                "currency_code": quote.currency_code,
                "total": str(quote.total),
            }
        )


# --- convert_quote_to_invoice -------------------------------------------------


class ConvertQuoteToInvoiceInput(BaseModel):
    quote_reference: str = Field(
        min_length=1,
        max_length=32,
        description='The quote number as shown to the user, e.g. "QUO-000023", or its raw id.',
    )


class ConvertQuoteToInvoiceResolved(BaseModel):
    quote_id: str


class ConvertQuoteToInvoiceTool(ActionTool):
    name = "convert_quote_to_invoice"
    description = (
        "Propose converting an accepted quote into a brand-new, independent "
        "invoice. Only quotes with status 'accepted' can be converted, and a "
        "quote can never be converted twice. Nothing is created until the "
        "user explicitly confirms."
    )
    input_schema = ConvertQuoteToInvoiceInput
    resolved_schema = ConvertQuoteToInvoiceResolved

    def build_proposal(
        self, db: Session, organization_id: str, current_user: User, raw_input: dict[str, Any]
    ) -> ProposalResult:
        data = ConvertQuoteToInvoiceInput.model_validate(raw_input)
        quote = _resolve_quote(db, organization_id, data.quote_reference)

        if quote.converted_invoice_id is not None:
            raise QuoteAlreadyConvertedError(quote.id)
        if quote.status != "accepted":
            raise QuoteNotAcceptedError(quote.id)

        resolved = ConvertQuoteToInvoiceResolved(quote_id=quote.id)
        summary = {
            "quote_number": format_quote_number(quote.quote_number),
            "customer_name": quote.customer_name,
            "total": str(quote.total),
            "currency_code": quote.currency_code,
        }
        return ProposalResult(resolved_input=resolved.model_dump(mode="json"), summary=summary)

    def execute(
        self, db: Session, organization_id: str, current_user: User, resolved: BaseModel
    ) -> ExecutionResult:
        assert isinstance(resolved, ConvertQuoteToInvoiceResolved)
        quote = _resolve_quote(db, organization_id, resolved.quote_id)

        try:
            result = convert_quote_to_invoice(db, organization_id, quote, current_user)
        except ServiceQuoteNotAcceptedError:
            raise QuoteNotAcceptedError(resolved.quote_id)
        except ServiceQuoteAlreadyConvertedError:
            raise QuoteAlreadyConvertedError(resolved.quote_id)

        from app.invoice_numbering import format_invoice_number

        return ExecutionResult(
            summary={
                "quote_number": format_quote_number(quote.quote_number),
                "invoice_number": format_invoice_number(result.invoice.invoice_number),
                "total": str(result.invoice.total),
            }
        )


# --- send_quote ---------------------------------------------------------------


class SendQuoteInput(BaseModel):
    quote_reference: str = Field(
        min_length=1,
        max_length=32,
        description='The quote number as shown to the user, e.g. "QUO-000023", or its raw id.',
    )


class SendQuoteResolved(BaseModel):
    quote_id: str


class SendQuoteTool(ActionTool):
    name = "send_quote"
    description = (
        "Propose (re)sending an existing quote to its customer by email, "
        "including an accept/reject link. The recipient is always the email "
        "already on file for that quote's customer. Nothing is sent until "
        "the user explicitly confirms."
    )
    input_schema = SendQuoteInput
    resolved_schema = SendQuoteResolved

    def build_proposal(
        self, db: Session, organization_id: str, current_user: User, raw_input: dict[str, Any]
    ) -> ProposalResult:
        data = SendQuoteInput.model_validate(raw_input)
        quote = _resolve_quote(db, organization_id, data.quote_reference)

        customer = quote.customer
        if customer is None or not customer.email:
            raise QuoteCustomerEmailMissingError(quote.id)

        resolved = SendQuoteResolved(quote_id=quote.id)
        summary = {
            "quote_number": format_quote_number(quote.quote_number),
            "recipient_email": customer.email,
        }
        return ProposalResult(resolved_input=resolved.model_dump(mode="json"), summary=summary)

    def execute(
        self, db: Session, organization_id: str, current_user: User, resolved: BaseModel
    ) -> ExecutionResult:
        assert isinstance(resolved, SendQuoteResolved)
        quote = _resolve_quote(db, organization_id, resolved.quote_id)

        try:
            result = send_quote_record(db, quote)
        except ServiceCustomerEmailMissingError:
            raise QuoteCustomerEmailMissingError(resolved.quote_id)
        except ServiceEmailSendFailedError as exc:
            raise ActionToolError("Failed to send quote email.") from exc

        return ExecutionResult(
            summary={
                "quote_number": format_quote_number(quote.quote_number),
                "recipient_email": result.sent_to,
            }
        )
