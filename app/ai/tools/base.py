"""ActionTool: the one interface every registered AI action must implement.

Providers (app/ai/anthropic_provider.py, app/ai/gemini_provider.py) never
import this module -- they only ever see the provider-agnostic
ToolDefinition (app/ai/base.py), which carries just a name/description/
JSON-schema triple. Only app/routers/assistant.py (propose) and
app/routers/assistant_actions.py (confirm/cancel) talk to tools directly,
and only through the registry (registry.py) -- never by importing a
concrete tool class.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.tools.types import ExecutionResult, ProposalResult
from app.models import User


class ActionTool(ABC):
    name: str
    description: str

    # What the model calls the tool with -- free-text references
    # (customer_name, invoice_reference), never a raw id. This schema's
    # model_json_schema() is what's sent to the provider as the tool's
    # parameters.
    input_schema: type[BaseModel]

    # What gets persisted in AssistantAction.input_payload and re-validated
    # at confirm time -- the fully *resolved* form (e.g. a real
    # customer_id), produced once by build_proposal() and never
    # re-resolved from free text again.
    resolved_schema: type[BaseModel]

    @abstractmethod
    def build_proposal(
        self,
        db: Session,
        organization_id: str,
        current_user: User,
        raw_input: dict[str, Any],
    ) -> ProposalResult:
        """Validates `raw_input` against `input_schema`, resolves every
        referenced entity strictly within organization_id, and returns the
        resolved input (as `resolved_schema`, JSON-dumped) plus a safe
        summary to persist as a proposal. Must never write to the
        database. Raises an ActionToolError subclass (see types.py) on any
        validation/resolution failure -- ambiguous or missing matches are
        never guessed."""
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        db: Session,
        organization_id: str,
        current_user: User,
        resolved: BaseModel,
    ) -> ExecutionResult:
        """Performs the actual write. `resolved` is an already-validated
        instance of `resolved_schema` (re-validated by the confirm
        endpoint from the stored proposal, never taken from the request
        body -- the client sends no business data at confirm time).
        Delegates to an extracted app.services function; never contains
        its own SQL or duplicated business logic."""
        raise NotImplementedError
