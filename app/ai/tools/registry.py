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

TOOL_REGISTRY: dict[str, ActionTool] = {
    tool.name: tool
    for tool in (
        CreateInvoiceDraftTool(),
        UpdateInvoiceStatusTool(),
        SendInvoiceEmailTool(),
        SendPaymentReminderTool(),
    )
}


def get_tool(name: str) -> ActionTool | None:
    return TOOL_REGISTRY.get(name)


def tool_definitions() -> list[ToolDefinition]:
    """Builds the provider-agnostic tool list passed into
    AIProvider.stream_complete(). Each provider translates these into its
    own native tool-declaration wire format at the call site."""
    return [
        ToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters=tool.input_schema.model_json_schema(),
        )
        for tool in TOOL_REGISTRY.values()
    ]
