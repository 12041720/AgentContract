"""RequirementExtractor converting natural language text into candidate Constraint models."""

from collections.abc import Callable, Mapping
from typing import Any
from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints.exceptions import ConstraintValidationError
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintSource,
)
from agentcontract.extraction.client import (
    ExtractionRequest,
    StructuredExtractionClient,
)
from agentcontract.extraction.exceptions import (
    ClientExtractionError,
    ExtractionValidationError,
)
from agentcontract.extraction.models import (
    ConstraintDraft,
    DiagnosticSeverity,
    ExtractionDiagnostic,
    ExtractionResult,
    get_requirement_extraction_schema,
)
from agentcontract.runtime.models import IdGenerator


class RequirementExtractor:
    """Provider-neutral extractor converting natural language requirements into validated Constraints.

    Authority rules:
    - Caller supplies: ConstraintSource, source_location, author, and raw source_text.
    - Model output CANNOT change caller provenance authority.
    - AGENT_INFERENCE cannot be HARD.
    - REQUIRE and PREFER must have a valid compliance_scope.
    - Does NOT mutate ConstraintLedger.
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
            self._id_gen = IdGenerator(deterministic=False)
        elif isinstance(id_generator, IdGenerator):
            self._id_gen = id_generator
        elif callable(id_generator):
            fn = id_generator

            class _CallableAdapter:
                def new_id(self, category: str = "c") -> str:
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
        """Identifier generator used for extracted constraints."""
        return self._id_gen

    def extract(
        self,
        text: str,
        *,
        source: ConstraintSource,
        source_location: str | None = None,
        author: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        strict: bool = True,
    ) -> ExtractionResult[Constraint]:
        """Extract structured requirements from natural language text.

        Args:
            text: Raw input text containing requirements or instructions.
            source: Authoritative provenance source (caller-owned, required).
            source_location: Source reference location (e.g. 'prompt:12').
            author: Author or agent role that introduced the constraint.
            metadata: Additional provenance metadata.
            context: Optional context passed to extraction client.
            strict: If True, invalid items or malformed drafts immediately raise ExtractionValidationError;
                    if False, issues are recorded as diagnostics and skipped.

        Returns:
            ExtractionResult containing durable Constraint instances and diagnostics.
        """
        if not isinstance(source, ConstraintSource):
            raise ExtractionValidationError(
                f"source must be a valid ConstraintSource enum instance, got {type(source).__name__}."
            )

        stripped_text = text.strip() if text else ""
        if not stripped_text:
            raise ExtractionValidationError("text to extract requirements from cannot be empty or blank.")

        schema = get_requirement_extraction_schema()
        task = "extract_requirements"

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
        items: list[Constraint] = []

        # Find raw candidates in response
        raw_candidates = (
            raw_response.get("constraints")
            or raw_response.get("requirements")
            or raw_response.get("items")
        )

        if raw_candidates is None:
            if "name" in raw_response and "description" in raw_response:
                raw_candidates = [raw_response]
            else:
                diag = ExtractionDiagnostic(
                    message="Response does not contain 'constraints' or 'requirements' list.",
                    severity=DiagnosticSeverity.ERROR,
                    field="constraints",
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
                message=f"Expected a list of constraints, got {type(raw_candidates).__name__}.",
                severity=DiagnosticSeverity.ERROR,
                field="constraints",
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

        provenance = ConstraintProvenance(
            source=source,
            source_location=source_location,
            source_text=text,  # Caller's original text, not rewritten model prose
            author=author,
            metadata=FrozenDict(metadata or {}),
        )

        for idx, candidate in enumerate(raw_candidates):
            if not isinstance(candidate, Mapping):
                diag = ExtractionDiagnostic(
                    message=f"Constraint candidate at index {idx} must be a mapping, got {type(candidate).__name__}.",
                    severity=DiagnosticSeverity.ERROR,
                    field=f"constraints[{idx}]",
                    raw_item=candidate,
                )
                if strict:
                    raise ExtractionValidationError(diag.message)
                diagnostics.append(diag)
                continue

            # Parse draft
            try:
                draft = ConstraintDraft.model_validate(candidate)
            except Exception as err:
                msg = f"Failed to parse candidate constraint at index {idx}: {err}"
                diag = ExtractionDiagnostic(
                    message=msg,
                    severity=DiagnosticSeverity.ERROR,
                    field=f"constraints[{idx}]",
                    raw_item=candidate,
                )
                if strict:
                    raise ExtractionValidationError(msg) from err
                diagnostics.append(diag)
                continue

            # Generate unique ID
            cid = self._id_gen.new_id("c")

            # Check if model attempted to tamper with authority or provenance
            if draft.id is not None:
                diagnostics.append(
                    ExtractionDiagnostic(
                        message=(
                            f"Model attempted to declare constraint id='{draft.id}'; "
                            f"caller-owned identifier '{cid}' was strictly enforced."
                        ),
                        severity=DiagnosticSeverity.WARNING,
                        field=f"constraints[{idx}].id",
                        code="AUTHORITY_SPOOF_IGNORED",
                        raw_item=draft.id,
                    )
                )

            if draft.source is not None and draft.source.strip().upper() != source.value:
                diagnostics.append(
                    ExtractionDiagnostic(
                        message=(
                            f"Model attempted to declare source='{draft.source}'; "
                            f"caller authority '{source.value}' was strictly enforced."
                        ),
                        severity=DiagnosticSeverity.WARNING,
                        field=f"constraints[{idx}].source",
                        code="AUTHORITY_SPOOF_IGNORED",
                        raw_item=draft.source,
                    )
                )

            if draft.author is not None and draft.author != author:
                diagnostics.append(
                    ExtractionDiagnostic(
                        message=(
                            f"Model attempted to declare author='{draft.author}'; "
                            f"caller-owned author '{author}' was strictly enforced."
                        ),
                        severity=DiagnosticSeverity.WARNING,
                        field=f"constraints[{idx}].author",
                        code="AUTHORITY_SPOOF_IGNORED",
                        raw_item=draft.author,
                    )
                )

            if draft.source_location is not None and draft.source_location != source_location:
                diagnostics.append(
                    ExtractionDiagnostic(
                        message=(
                            f"Model attempted to declare source_location='{draft.source_location}'; "
                            f"caller-owned source_location '{source_location}' was strictly enforced."
                        ),
                        severity=DiagnosticSeverity.WARNING,
                        field=f"constraints[{idx}].source_location",
                        code="AUTHORITY_SPOOF_IGNORED",
                        raw_item=draft.source_location,
                    )
                )

            if draft.source_text is not None and draft.source_text != text:
                diagnostics.append(
                    ExtractionDiagnostic(
                        message=(
                            "Model attempted to declare source_text; "
                            "caller-owned raw source_text was strictly enforced."
                        ),
                        severity=DiagnosticSeverity.WARNING,
                        field=f"constraints[{idx}].source_text",
                        code="AUTHORITY_SPOOF_IGNORED",
                        raw_item=draft.source_text,
                    )
                )

            # Convert to durable Constraint model
            try:
                constraint = draft.to_constraint(
                    constraint_id=cid,
                    provenance=provenance,
                )
                items.append(constraint)
            except (ExtractionValidationError, ConstraintValidationError) as err:
                diag = ExtractionDiagnostic(
                    message=f"Validation failed for constraint candidate '{draft.name}': {err}",
                    severity=DiagnosticSeverity.ERROR,
                    field=f"constraints[{idx}]",
                    raw_item=candidate,
                )
                if strict:
                    raise ExtractionValidationError(diag.message) from err
                diagnostics.append(diag)
            except Exception as err:
                diag = ExtractionDiagnostic(
                    message=f"Unexpected error constructing constraint '{draft.name}': {err}",
                    severity=DiagnosticSeverity.ERROR,
                    field=f"constraints[{idx}]",
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
