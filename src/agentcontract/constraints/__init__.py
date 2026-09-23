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
    Constraint,
    ConstraintId,
    ConstraintProvenance,
    ConstraintRelation,
    ConstraintScope,
    ConstraintSource,
    ConstraintStatus,
    ConstraintStrength,
)

__all__ = [
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
    "InvalidConstraintTransitionError",
    "LedgerSnapshot",
]
