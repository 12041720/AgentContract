"""External agent/tool adapters, OpenTelemetry bridge, and extraction provider integrations."""

from agentcontract.adapters.exceptions import (
    AdapterConfigurationError,
    AdapterError,
    AdapterValidationError,
)
from agentcontract.adapters.openai import OpenAICompatibleExtractionClient
from agentcontract.adapters.otel import (
    OTelSpan,
    OTelTraceBridge,
    OTelTraceExport,
)
from agentcontract.adapters.tool_events import (
    ExternalToolCallRecord,
    ExternalToolResultRecord,
    ToolEventAdapter,
)

__all__ = [
    # Exceptions
    "AdapterConfigurationError",
    "AdapterError",
    "AdapterValidationError",
    # Tool events
    "ExternalToolCallRecord",
    "ExternalToolResultRecord",
    "ToolEventAdapter",
    # OpenTelemetry
    "OTelSpan",
    "OTelTraceBridge",
    "OTelTraceExport",
    # Extraction provider
    "OpenAICompatibleExtractionClient",
]
