"""Runtime subsystem exceptions."""


class AgentContractRuntimeError(Exception):
    """Base exception for all runtime wrapper errors."""


class RuntimeValidationError(AgentContractRuntimeError):
    """Raised when runtime inputs or states fail validation."""


class ToolExecutionError(AgentContractRuntimeError):
    """Raised when an unrecoverable error occurs in tool invocation."""
