"""Domain exceptions for the trace subsystem."""


class TraceError(Exception):
    """Base exception for all trace domain errors."""


class TraceValidationError(TraceError, ValueError):
    """Base exception for validation and invariant failures in the trace domain."""


class DuplicateEventError(TraceValidationError):
    """Raised when an event ID is already registered in the trace store."""


class InvalidSequenceError(TraceValidationError):
    """Raised when event sequence numbers are negative or not strictly increasing."""


class EventNotFoundError(TraceError, KeyError):
    """Raised when an event cannot be located by identifier."""


class ToolCorrelationError(TraceValidationError):
    """Raised when tool call or tool result correlation invariants are violated."""


class ParentEventError(TraceValidationError):
    """Raised when parent-event references are invalid or cross trace boundaries."""
