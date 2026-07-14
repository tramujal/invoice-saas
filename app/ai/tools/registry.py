"""The single registry of every AI-invokable action tool.

app/routers/assistant.py (propose) and app/routers/assistant_actions.py
(confirm/cancel) look up tools by name through this module only — neither
ever imports a concrete tool class directly, and neither provider
(app/ai/anthropic_provider.py, app/ai/gemini_provider.py) imports this
module at all. Adding a new action later means adding one tool instance to
TOOL_REGISTRY below; nothing else in the provider/router layer changes.
"""

from app.ai.base import ToolDefinition
from app.ai.tools.base import ActionTool
from app.ai.tools.invoices import (
    CreateInvoiceDraftTool,
    SendInvoiceEmailTool,
    SendPaymentReminderTool,
    UpdateInvoiceStatusTool,
)
from app.ai.tools.quotes import (
    ConvertQuoteToInvoiceTool,
    CreateQuoteDraftTool,
    SendQuoteTool,
)
from app.permissions import Permission

TOOL_REGISTRY: dict[str, ActionTool] = {
    tool.name: tool
    for tool in (
        CreateInvoiceDraftTool(),
        UpdateInvoiceStatusTool(),
        SendInvoiceEmailTool(),
        SendPaymentReminderTool(),
        CreateQuoteDraftTool(),
        ConvertQuoteToInvoiceTool(),
        SendQuoteTool(),
    )
}

# The permission each tool requires to be proposed (app/routers/assistant.py)
# and confirmed (app/routers/assistant_actions.py) -- the single source of
# truth both call sites check against, so a new tool only ever needs one
# new entry here, never a bespoke authorization check inside the tool
# itself. See app.permissions.ROLE_PERMISSIONS for what each role holds.
TOOL_PERMISSIONS: dict[str, Permission] = {
    CreateInvoiceDraftTool.name: Permission.invoice_create,
    UpdateInvoiceStatusTool.name: Permission.invoice_edit,
    SendInvoiceEmailTool.name: Permission.invoice_send,
    SendPaymentReminderTool.name: Permission.invoice_send,
    CreateQuoteDraftTool.name: Permission.quote_create,
    ConvertQuoteToInvoiceTool.name: Permission.quote_convert,
    SendQuoteTool.name: Permission.quote_send,
}


def get_tool(name: str) -> ActionTool | None:
    return TOOL_REGISTRY.get(name)


def tool_definitions(allowed: frozenset[Permission] | None = None) -> list[ToolDefinition]:
    """Builds the provider-agnostic tool list passed into
    AIProvider.stream_complete(). Each provider translates these into its
    own native tool-declaration wire format at the call site.

    When `allowed` is given (the caller's role's permission set -- see
    app.routers.assistant), tools whose required permission isn't in it
    are filtered out entirely, so e.g. a Viewer's model is never even
    offered a write tool to call. This is defense in depth, not the actual
    security boundary -- build_proposal/execute are still independently
    permission-checked regardless of what was offered, since a malformed
    or replayed client request could invoke a tool the model was never
    shown."""
    return [
        ToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters=tool.input_schema.model_json_schema(),
        )
        for tool in TOOL_REGISTRY.values()
        if allowed is None or TOOL_PERMISSIONS.get(tool.name) in allowed
    ]
