"""Constraint domain models and ledger.

Defines the core domain layer for AgentContract: typed, immutable constraint and
provenance models, along with an in-memory, version-preserving ConstraintLedger.
"""

from agentcontract.constraints.exceptions import (
    ConstraintError,
    ConstraintNotFoundError,
    ConstraintValidationError,
    DuplicateConstraintError,
    InvalidConstraintTransitionError,
)
from agentcontract.constraints.ledger import (
    ConstraintLedger,
    LedgerSnapshot,
)
from agentcontract.constraints.models import (
    ALLOWED_TRANSITIONS,
    Constraint,
    ConstraintId,
    ConstraintProvenance,
    ConstraintRelation,
    ConstraintScope,
    ConstraintSource,
    ConstraintStatus,
    ConstraintStrength,
    FrozenDict,
    validate_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "Constraint",
    "ConstraintError",
    "ConstraintId",
    "ConstraintLedger",
    "ConstraintNotFoundError",
    "ConstraintProvenance",
    "ConstraintRelation",
    "ConstraintScope",
    "ConstraintSource",
    "ConstraintStatus",
    "ConstraintStrength",
    "ConstraintValidationError",
    "DuplicateConstraintError",
    "FrozenDict",
    "InvalidConstraintTransitionError",
    "LedgerSnapshot",
    "validate_transition",
]
