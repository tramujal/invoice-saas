"""Shared types for the AI assistant's action-tool layer.

A "tool" here is a small, explicitly registered unit of business capability
the model may invoke (see base.py/registry.py) -- never a generic
function-call escape hatch, and never anything that touches the database
by itself. Every tool follows the same two-phase shape: build_proposal()
resolves free-text references (customer name, invoice number) strictly
within one organization and returns a ProposalResult -- never writes --
and execute() performs the actual write later, using an extracted
app.services function, only after the confirm endpoint has verified
ownership/expiry/single-use.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ProposalResult:
    """What build_proposal() returns.

    `resolved_input` is the tool's *resolved* schema dumped to a JSON-safe
    dict (see ActionTool.resolved_schema) -- e.g. a resolved customer_id,
    never the raw customer_name the model supplied -- and is exactly what
    gets persisted in AssistantAction.input_payload. `summary` is the safe,
    user-facing preview shown in the proposal card, re-shown identically
    after execution.
    """

    resolved_input: dict[str, Any]
    summary: dict[str, Any]


@dataclass
class ExecutionResult:
    """What execute() returns on success: a safe, user-facing result
    summary -- never a raw ORM object -- persisted nowhere beyond
    AssistantAction's own fields."""

    summary: dict[str, Any]


class ActionToolError(Exception):
    """Base class for every typed error a tool can raise from
    build_proposal() or execute(). Each maps to one of the assistant's
    stable, language-neutral error codes (see app/routers/assistant.py and
    app/routers/assistant_actions.py) -- callers never see this exception's
    message text directly, only `.code`."""

    code: str = "assistant_action_invalid"


class AmbiguousCustomerError(ActionToolError):
    """0 matches would be CustomerNotFoundError; this is 2+ matches for a
    customer_name search -- the caller must ask the user to clarify rather
    than guessing which one was meant."""

    code = "ambiguous_customer"

    def __init__(self, candidate_names: list[str]):
        super().__init__("Multiple customers match this name.")
        # Capped and name-only -- never ids/emails -- the user already has
        # full org-scoped access to this list via the customers page, so
        # this isn't a new disclosure, just a smaller/safer echo of it.
        self.candidate_names = candidate_names[:5]


class CustomerNotFoundError(ActionToolError):
    code = "customer_not_found"


class InvoiceNotFoundError(ActionToolError):
    code = "invoice_not_found"


class CustomerEmailMissingError(ActionToolError):
    code = "customer_email_missing"
