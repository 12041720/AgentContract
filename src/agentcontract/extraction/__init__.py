"""Provider-neutral LLM-assisted requirement and claim extraction adapters."""

from agentcontract.extraction.claims import ClaimExtractor
from agentcontract.extraction.client import (
    ExtractionRequest,
    FakeStructuredExtractionClient,
    StructuredExtractionClient,
)
from agentcontract.extraction.exceptions import (
    ClientExtractionError,
    ExtractionError,
    ExtractionValidationError,
)
from agentcontract.extraction.helpers import extract_and_verify_claims
from agentcontract.extraction.models import (
    ClaimDraft,
    ConstraintDraft,
    ConstraintScopeDraft,
    DiagnosticSeverity,
    ExtractionDiagnostic,
    ExtractionResult,
    get_claim_extraction_schema,
    get_requirement_extraction_schema,
)
from agentcontract.extraction.requirements import RequirementExtractor

__all__ = [
    # Protocols and Clients
    "StructuredExtractionClient",
    "FakeStructuredExtractionClient",
    "ExtractionRequest",
    # Draft Models
    "ConstraintScopeDraft",
    "ConstraintDraft",
    "ClaimDraft",
    # Results and Diagnostics
    "DiagnosticSeverity",
    "ExtractionDiagnostic",
    "ExtractionResult",
    "get_requirement_extraction_schema",
    "get_claim_extraction_schema",
    # Extractors
    "RequirementExtractor",
    "ClaimExtractor",
    # Helpers
    "extract_and_verify_claims",
    # Exceptions
    "ExtractionError",
    "ExtractionValidationError",
    "ClientExtractionError",
]
