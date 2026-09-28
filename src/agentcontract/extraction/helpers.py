"""Optional integration helpers connecting extraction with runtime verification."""

from collections.abc import Mapping
from typing import Any

from agentcontract.evidence.models import Claim
from agentcontract.extraction.claims import ClaimExtractor
from agentcontract.extraction.models import ExtractionResult
from agentcontract.runtime.models import VerificationResult
from agentcontract.runtime.session import AgentContractRuntime


def extract_and_verify_claims(
    extractor: ClaimExtractor,
    text: str,
    runtime: AgentContractRuntime,
    *,
    context: Mapping[str, Any] | None = None,
    strict: bool = True,
) -> tuple[ExtractionResult[Claim], VerificationResult]:
    """Extract atomic claims from completion text using the runtime's trace context and verify them.

    Args:
        extractor: Configured ClaimExtractor instance.
        text: Natural language completion text.
        runtime: Active AgentContractRuntime owning the TraceStore and EvidenceGate.
        context: Optional client extraction context.
        strict: Whether to enforce strict parsing of claim drafts.

    Returns:
        Tuple of (ExtractionResult containing the extracted Claim objects, VerificationResult from runtime).
    """
    extraction_res = extractor.extract(
        text,
        trace_id=runtime.trace_id,
        session_id=runtime.session_id,
        context=context,
        strict=strict,
    )
    verification_res = runtime.verify_claims(extraction_res.items)
    return extraction_res, verification_res
