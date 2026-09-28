"""ClaimExtractor converting natural language completion text into atomic Claim models."""

from collections.abc import Callable, Mapping
from typing import Any
from agentcontract.common.immutable import FrozenDict
from agentcontract.evidence.exceptions import EvidenceValidationError
from agentcontract.evidence.models import Claim
from agentcontract.extraction.client import (
    StructuredExtractionClient,
)
from agentcontract.extraction.exceptions import (
    ClientExtractionError,
    ExtractionValidationError,
)
from agentcontract.extraction.models import (
    ClaimDraft,
    DiagnosticSeverity,
    ExtractionDiagnostic,
    ExtractionResult,
    get_claim_extraction_schema,
)
from agentcontract.runtime.models import IdGenerator


class ClaimExtractor:
    """Provider-neutral extractor converting natural language completion text into atomic Claim models.

    Authority & Scope rules:
    - Caller supplies: trace_id and session_id (cannot be overridden by model proposals).
    - Extracted claims have NO verdict field; they remain unverified until EvidenceGate evaluates them.
    - Preserves deterministic item order.
    - Unsupported or subjective statements become GENERIC claims or diagnostics.
    """

    def __init__(
        self,
        client: StructuredExtractionClient,
        id_generator: IdGenerator | Callable[[str], str] | None = None,
    ) -> None:
        if not hasattr(client, "extract") or not callable(client.extract):
            raise ExtractionValidationError("client must implement StructuredExtractionClient protocol.")
        self._client = client

        if id_generator is None:
            self._id_gen = IdGenerator(deterministic=True)
        elif isinstance(id_generator, IdGenerator):
            self._id_gen = id_generator
        elif callable(id_generator):
            fn = id_generator

            class _CallableAdapter:
                def new_id(self, category: str = "claim") -> str:
                    return fn(category)

            self._id_gen = _CallableAdapter()  # type: ignore[assignment]
        else:
            raise ExtractionValidationError(f"Invalid id_generator type: {type(id_generator).__name__}")

    @property
    def client(self) -> StructuredExtractionClient:
        """Underlying structured extraction client."""
        return self._client

    @property
    def id_generator(self) -> Any:
        """Identifier generator used for extracted claims."""
        return self._id_gen

    def extract(
        self,
        text: str,
        *,
        trace_id: str | None = None,
        session_id: str | None = None,
        context: Mapping[str, Any] | None = None,
        strict: bool = True,
    ) -> ExtractionResult[Claim]:
        """Extract structured atomic claims from completion text.

        Args:
            text: Completion text or summary produced by the agent.
            trace_id: Authoritative trace identifier scoping the claims.
            session_id: Authoritative session identifier scoping the claims.
            context: Optional context passed to extraction client.
            strict: If True, invalid claim types or malformed drafts immediately raise ExtractionValidationError;
                    if False, issues are recorded as diagnostics and skipped.

        Returns:
            ExtractionResult containing durable Claim instances and diagnostics.
        """
        stripped_text = text.strip() if text else ""
        if not stripped_text:
            raise ExtractionValidationError("text to extract claims from cannot be empty or blank.")

        schema = get_claim_extraction_schema()
        task = "extract_claims"

        # Client must be invoked exactly once per extraction request
        try:
            raw_response = self._client.extract(
                task=task,
                text=text,
                schema=schema,
                context=context,
            )
        except Exception as exc:
            if isinstance(exc, ClientExtractionError):
                raise
            raise ClientExtractionError(f"Extraction client failed: {exc}") from exc

        if not isinstance(raw_response, Mapping):
            raise ClientExtractionError(
                f"Extraction client must return a Mapping, got {type(raw_response).__name__}."
            )

        diagnostics: list[ExtractionDiagnostic] = []
        items: list[Claim] = []

        # Find raw candidates in response
        raw_candidates = raw_response.get("claims") or raw_response.get("items")

        if raw_candidates is None:
            if "claim_type" in raw_response and "description" in raw_response:
                raw_candidates = [raw_response]
            else:
                diag = ExtractionDiagnostic(
                    message="Response does not contain 'claims' list.",
                    severity=DiagnosticSeverity.ERROR,
                    field="claims",
                    raw_item=dict(raw_response),
                )
                if strict:
                    raise ExtractionValidationError(diag.message)
                diagnostics.append(diag)
                return ExtractionResult(
                    items=(),
                    diagnostics=tuple(diagnostics),
                    raw_response=FrozenDict(raw_response),
                )

        if not isinstance(raw_candidates, (list, tuple)):
            diag = ExtractionDiagnostic(
                message=f"Expected a list of claims, got {type(raw_candidates).__name__}.",
                severity=DiagnosticSeverity.ERROR,
                field="claims",
                raw_item=raw_candidates,
            )
            if strict:
                raise ExtractionValidationError(diag.message)
            diagnostics.append(diag)
            return ExtractionResult(
                items=(),
                diagnostics=tuple(diagnostics),
                raw_response=FrozenDict(raw_response),
            )

        for idx, candidate in enumerate(raw_candidates):
            if not isinstance(candidate, Mapping):
                diag = ExtractionDiagnostic(
                    message=f"Claim candidate at index {idx} must be a mapping, got {type(candidate).__name__}.",
                    severity=DiagnosticSeverity.ERROR,
                    field=f"claims[{idx}]",
                    raw_item=candidate,
                )
                if strict:
                    raise ExtractionValidationError(diag.message)
                diagnostics.append(diag)
                continue

            # Parse draft
            try:
                draft = ClaimDraft.model_validate(candidate)
            except Exception as err:
                msg = f"Failed to parse candidate claim at index {idx}: {err}"
                diag = ExtractionDiagnostic(
                    message=msg,
                    severity=DiagnosticSeverity.ERROR,
                    field=f"claims[{idx}]",
                    raw_item=candidate,
                )
                if strict:
                    raise ExtractionValidationError(msg) from err
                diagnostics.append(diag)
                continue

            # Check if model attempted to tamper with trace_id or session_id
            if draft.trace_id is not None and draft.trace_id != trace_id:
                diagnostics.append(
                    ExtractionDiagnostic(
                        message=(
                            f"Model attempted to declare trace_id='{draft.trace_id}'; "
                            f"caller trace_id '{trace_id}' was strictly enforced."
                        ),
                        severity=DiagnosticSeverity.WARNING,
                        field=f"claims[{idx}].trace_id",
                        code="SCOPE_SPOOF_IGNORED",
                        raw_item=draft.trace_id,
                    )
                )

            # Generate unique deterministic ID
            cid = self._id_gen.new_id("claim")

            # Convert to durable Claim model
            try:
                claim = draft.to_claim(
                    claim_id=cid,
                    trace_id=trace_id,
                    session_id=session_id,
                )
                items.append(claim)
            except (ExtractionValidationError, EvidenceValidationError) as err:
                diag = ExtractionDiagnostic(
                    message=f"Validation failed for claim candidate '{draft.description}': {err}",
                    severity=DiagnosticSeverity.ERROR,
                    field=f"claims[{idx}]",
                    raw_item=candidate,
                )
                if strict:
                    raise ExtractionValidationError(diag.message) from err
                diagnostics.append(diag)
            except Exception as err:
                diag = ExtractionDiagnostic(
                    message=f"Unexpected error constructing claim '{draft.description}': {err}",
                    severity=DiagnosticSeverity.ERROR,
                    field=f"claims[{idx}]",
                    raw_item=candidate,
                )
                if strict:
                    raise ExtractionValidationError(diag.message) from err
                diagnostics.append(diag)

        return ExtractionResult(
            items=tuple(items),
            diagnostics=tuple(diagnostics),
            raw_response=FrozenDict(raw_response),
        )
