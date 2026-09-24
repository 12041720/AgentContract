"""AgentContract: reliability primitives for long-horizon tool-using agents."""

from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints import (
    Constraint,
    ConstraintLedger,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStatus,
    ConstraintStrength,
)
from agentcontract.trace import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceDurableValue,
    TraceEvent,
    TracePointer,
    TraceStore,
)

__version__ = "0.1.0"

__all__ = [
    # Common
    "FrozenDict",
    # Constraints
    "Constraint",
    "ConstraintLedger",
    "ConstraintProvenance",
    "ConstraintScope",
    "ConstraintSource",
    "ConstraintStatus",
    "ConstraintStrength",
    # Trace
    "ActorKind",
    "EventKind",
    "ToolCall",
    "ToolResult",
    "ToolResultStatus",
    "TraceDurableValue",
    "TraceEvent",
    "TracePointer",
    "TraceStore",
    # Meta
    "__version__",
]
