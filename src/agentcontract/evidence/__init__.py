"""Claims, evidence graph, and EvidenceGate verification engine."""

from agentcontract.evidence.exceptions import (
    ClaimNotFoundError,
    EvidenceError,
    EvidenceValidationError,
)
from agentcontract.evidence.gate import EvidenceGate
from agentcontract.evidence.graph import EvidenceGraph
from agentcontract.evidence.models import (
    Claim,
    ClaimEvaluation,
    ClaimType,
    ClaimVerdict,
    EvidenceRef,
    EvidenceRelation,
)

__all__ = [
    # Exceptions
    "ClaimNotFoundError",
    "EvidenceError",
    "EvidenceValidationError",
    # Enums
    "ClaimType",
    "ClaimVerdict",
    "EvidenceRelation",
    # Models
    "Claim",
    "ClaimEvaluation",
    "EvidenceRef",
    # Graph & Gate
    "EvidenceGate",
    "EvidenceGraph",
]
