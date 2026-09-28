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
    RuleEffect,
)
from agentcontract.evidence import (
    Claim,
    ClaimEvaluation,
    ClaimNotFoundError,
    ClaimType,
    ClaimVerdict,
    EvidenceError,
    EvidenceGate,
    EvidenceGraph,
    EvidenceRef,
    EvidenceRelation,
    EvidenceValidationError,
)
from agentcontract.guard import (
    Action,
    ActionKind,
    ActionObservation,
    DecisionKind,
    GuardDecision,
    GuardError,
    GuardValidationError,
    SpecGuard,
    match_scope,
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
    "RuleEffect",
    # Guard
    "Action",
    "ActionKind",
    "ActionObservation",
    "DecisionKind",
    "GuardDecision",
    "GuardError",
    "GuardValidationError",
    "SpecGuard",
    "match_scope",
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
    # Evidence
    "Claim",
    "ClaimEvaluation",
    "ClaimNotFoundError",
    "ClaimType",
    "ClaimVerdict",
    "EvidenceError",
    "EvidenceGate",
    "EvidenceGraph",
    "EvidenceRef",
    "EvidenceRelation",
    "EvidenceValidationError",
    # Meta
    "__version__",
]
