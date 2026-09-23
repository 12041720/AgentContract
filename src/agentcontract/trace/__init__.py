"""Normalized trace and provenance domain."""

from agentcontract.trace.exceptions import (
    DuplicateEventError,
    EventNotFoundError,
    InvalidSequenceError,
    ParentEventError,
    ToolCorrelationError,
    TraceError,
    TraceValidationError,
)
from agentcontract.trace.models import (
    ActorKind,
    EventId,
    EventKind,
    SessionId,
    ToolCall,
    ToolCallId,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
    TraceId,
    TracePointer,
)
from agentcontract.trace.store import TraceStore

__all__ = [
    # Identifiers
    "TraceId",
    "SessionId",
    "EventId",
    "ToolCallId",
    # Enums
    "ActorKind",
    "EventKind",
    "ToolResultStatus",
    # Models
    "TracePointer",
    "ToolCall",
    "ToolResult",
    "TraceEvent",
    # Store
    "TraceStore",
    # Exceptions
    "TraceError",
    "TraceValidationError",
    "DuplicateEventError",
    "InvalidSequenceError",
    "EventNotFoundError",
    "ToolCorrelationError",
    "ParentEventError",
]
