"""Candidate draft models, diagnostics, and extraction results."""

from collections.abc import Iterator, Mapping, Sequence
from enum import StrEnum
from typing import Any, Generic, TypeVar
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict, _freeze_value
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.evidence.models import Claim, ClaimType
from agentcontract.extraction.exceptions import ExtractionValidationError

T = TypeVar("T")


class DiagnosticSeverity(StrEnum):
    """Severity level of an extraction diagnostic."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ExtractionDiagnostic(BaseModel):
    """Diagnostic detail produced during extraction parsing or validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(..., description="Explanation of the issue or discrepancy.")
    severity: DiagnosticSeverity = Field(
        default=DiagnosticSeverity.WARNING,
        description="Severity level: ERROR, WARNING, or INFO.",
    )
    field: str | None = Field(
        default=None,
        description="Optional field path associated with the diagnostic.",
    )
    code: str | None = Field(
        default=None,
        description="Optional standardized diagnostic code.",
    )
    raw_item: Any = Field(
        default=None,
        description="Raw untrusted item data that triggered this diagnostic.",
    )


class ConstraintScopeDraft(BaseModel):
    """Candidate scope proposed by extraction model before validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_type: str | None = Field(default=None, description="Category of target resource.")
    paths: tuple[str, ...] = Field(default_factory=tuple, description="File or resource paths.")
    tools: tuple[str, ...] = Field(default_factory=tuple, description="Tool identifiers.")
    actions: tuple[str, ...] = Field(default_factory=tuple, description="Action verbs.")
    selectors: FrozenDict = Field(default_factory=FrozenDict, description="Custom selector filters.")
    description: str | None = Field(default=None, description="Scope summary.")

    @field_validator("paths", "tools", "actions", mode="before")
    @classmethod
    def _normalize_string_sequence(cls, val: Any) -> tuple[str, ...]:
        if val is None:
            return ()
        if isinstance(val, (set, frozenset)):
            raise ExtractionValidationError("Scope collections must be ordered sequences (list or tuple), not sets.")
        if isinstance(val, str):
            s = val.strip()
            return (s,) if s else ()
        if isinstance(val, (list, tuple)):
            res = []
            for item in val:
                s = str(item).strip()
                if s:
                    res.append(s)
            return tuple(res)
        raise ExtractionValidationError(f"Expected sequence of strings, got {type(val).__name__}")

    @field_validator("selectors", mode="before")
    @classmethod
    def _freeze_selectors(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_value(v) for k, v in val.items()})
        raise ExtractionValidationError(f"selectors must be a mapping, got {type(val).__name__}")

    def to_scope(self) -> ConstraintScope:
        """Convert validated draft to durable ConstraintScope."""
        return ConstraintScope(
            target_type=self.target_type,
            paths=self.paths,
            tools=self.tools,
            actions=self.actions,
            selectors=self.selectors,
            description=self.description,
        )


class ConstraintDraft(BaseModel):
    """Candidate constraint proposed by extraction model before authority enforcement."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(..., description="Proposed constraint name.")
    description: str = Field(..., description="Proposed requirement specification.")
    strength: ConstraintStrength = Field(
        default=ConstraintStrength.HARD,
        description="Proposed enforcement strength: HARD, SOFT, ASSUMPTION.",
    )
    rule_effect: RuleEffect = Field(
        default=RuleEffect.DENY,
        description="Proposed rule effect: DENY, REQUIRE, PREFER.",
    )
    scope: ConstraintScopeDraft | None = Field(
        default=None,
        description="Applicability scope.",
    )
    compliance_scope: ConstraintScopeDraft | None = Field(
        default=None,
        description="Compliance scope for REQUIRE and PREFER rules.",
    )
    # Model might attempt to propose authority or provenance metadata
    source: str | None = Field(default=None, description="Proposed source category (untrusted).")
    id: str | None = Field(default=None, description="Proposed identifier (untrusted).")
    author: str | None = Field(default=None, description="Proposed author (untrusted).")
    source_location: str | None = Field(default=None, description="Proposed source location (untrusted).")
    source_text: str | None = Field(default=None, description="Proposed source text (untrusted).")

    @field_validator("name", "description")
    @classmethod
    def _validate_non_empty(cls, val: str) -> str:
        s = val.strip()
        if not s:
            raise ExtractionValidationError("name and description must not be empty.")
        return s

    @field_validator("strength", mode="before")
    @classmethod
    def _validate_strength(cls, val: Any) -> ConstraintStrength:
        if isinstance(val, ConstraintStrength):
            return val
        if isinstance(val, str):
            try:
                return ConstraintStrength(val.strip().upper())
            except ValueError:
                raise ExtractionValidationError(f"Invalid constraint strength: '{val}'")
        raise ExtractionValidationError(f"Expected constraint strength string, got {type(val).__name__}")

    @field_validator("rule_effect", mode="before")
    @classmethod
    def _validate_rule_effect(cls, val: Any) -> RuleEffect:
        if isinstance(val, RuleEffect):
            return val
        if isinstance(val, str):
            try:
                return RuleEffect(val.strip().upper())
            except ValueError:
                raise ExtractionValidationError(f"Invalid rule effect: '{val}'")
        raise ExtractionValidationError(f"Expected rule effect string, got {type(val).__name__}")

    def to_constraint(
        self,
        *,
        constraint_id: str,
        provenance: ConstraintProvenance,
    ) -> Constraint:
        """Convert validated draft to a durable authoritative Constraint model.

        Enforces all domain invariants:
        1. Provenance is strictly caller-provided (never overridden by model proposals).
        2. AGENT_INFERENCE cannot masquerade as HARD strength.
        3. REQUIRE and PREFER rules require an explicit compliance_scope.
        """
        # Invariant: AGENT_INFERENCE cannot be HARD
        if provenance.source == ConstraintSource.AGENT_INFERENCE and self.strength == ConstraintStrength.HARD:
            raise ExtractionValidationError(
                "AGENT_INFERENCE cannot be declared with HARD strength; inferences must be SOFT or ASSUMPTION."
            )

        # Invariant: REQUIRE / PREFER require compliance_scope
        if self.rule_effect in (RuleEffect.REQUIRE, RuleEffect.PREFER) and self.compliance_scope is None:
            raise ExtractionValidationError(
                f"Constraint with rule_effect={self.rule_effect.value} requires a compliance_scope."
            )

        scope_obj = self.scope.to_scope() if self.scope is not None else ConstraintScope()
        comp_scope_obj = (
            self.compliance_scope.to_scope() if self.compliance_scope is not None else None
        )

        return Constraint(
            id=constraint_id,
            name=self.name,
            description=self.description,
            strength=self.strength,
            rule_effect=self.rule_effect,
            provenance=provenance,
            scope=scope_obj,
            compliance_scope=comp_scope_obj,
        )


class ClaimDraft(BaseModel):
    """Candidate completion or state claim proposed by extraction model."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    claim_type: ClaimType = Field(..., description="Proposed claim category.")
    description: str = Field(..., description="Atomic claim statement.")
    call_id: str | None = Field(default=None, description="Optional specific tool call id.")
    tool_name: str | None = Field(default=None, description="Optional tool name.")
    command: str | None = Field(default=None, description="Optional executed command.")
    target_path: str | None = Field(default=None, description="Optional target file path.")
    expected_exit_code: int | None = Field(default=None, description="Optional expected exit code.")
    metadata: FrozenDict = Field(default_factory=FrozenDict, description="Optional custom attributes.")
    # Untrusted fields if model attempted to output them
    claim_id: str | None = Field(default=None, description="Proposed identifier (untrusted).")
    trace_id: str | None = Field(default=None, description="Proposed trace ID (untrusted).")
    session_id: str | None = Field(default=None, description="Proposed session ID (untrusted).")

    @field_validator("description")
    @classmethod
    def _validate_non_empty(cls, val: str) -> str:
        s = val.strip()
        if not s:
            raise ExtractionValidationError("description must not be empty.")
        return s

    @field_validator("claim_type", mode="before")
    @classmethod
    def _validate_claim_type(cls, val: Any) -> ClaimType:
        if isinstance(val, ClaimType):
            return val
        if isinstance(val, str):
            try:
                return ClaimType(val.strip().upper())
            except ValueError:
                raise ExtractionValidationError(f"Invalid claim type: '{val}'")
        raise ExtractionValidationError(f"Expected claim type string, got {type(val).__name__}")

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_value(v) for k, v in val.items()})
        raise ExtractionValidationError(f"metadata must be a mapping, got {type(val).__name__}")

    def to_claim(
        self,
        *,
        claim_id: str,
        trace_id: str | None = None,
        session_id: str | None = None,
    ) -> Claim:
        """Convert validated draft to a durable authoritative Claim model."""
        return Claim(
            claim_id=claim_id,
            claim_type=self.claim_type,
            description=self.description,
            trace_id=trace_id,
            session_id=session_id,
            call_id=self.call_id,
            tool_name=self.tool_name,
            command=self.command,
            target_path=self.target_path,
            expected_exit_code=self.expected_exit_code,
            metadata=self.metadata,
        )


class ExtractionResult(BaseModel, Generic[T]):
    """Aggregated container for extracted durable domain models and diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[T, ...] = Field(
        default_factory=tuple,
        description="Extracted durable domain items in deterministic encounter order.",
    )
    diagnostics: tuple[ExtractionDiagnostic, ...] = Field(
        default_factory=tuple,
        description="Diagnostics or warnings recorded during extraction and validation.",
    )
    raw_response: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Raw structured mapping returned by the client.",
    )

    @field_validator("raw_response", mode="before")
    @classmethod
    def _freeze_raw_response(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_value(v) for k, v in val.items()})
        raise ExtractionValidationError(f"raw_response must be a mapping, got {type(val).__name__}")

    @field_serializer("raw_response", mode="plain")
    def _serialize_raw_response(self, val: Any) -> dict[str, Any]:
        def _to_plain(v: Any) -> Any:
            if isinstance(v, (FrozenDict, Mapping)):
                return {str(k): _to_plain(item) for k, item in v.items()}
            if isinstance(v, (list, tuple)):
                return [_to_plain(item) for item in v]
            return v

        return _to_plain(val)

    @property
    def is_success(self) -> bool:
        """True if extraction did not encounter any ERROR-level diagnostics."""
        return not self.has_errors

    @property
    def has_errors(self) -> bool:
        """True if any diagnostic has ERROR severity."""
        return any(d.severity == DiagnosticSeverity.ERROR for d in self.diagnostics)

    @property
    def has_warnings(self) -> bool:
        """True if any diagnostic has WARNING severity."""
        return any(d.severity == DiagnosticSeverity.WARNING for d in self.diagnostics)

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, idx: int) -> T:
        return self.items[idx]


def get_requirement_extraction_schema() -> dict[str, Any]:
    """Return JSON Schema specifying expected requirement extraction structured output."""
    return {
        "type": "object",
        "properties": {
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short machine- or human-readable identifier (e.g. 'no_hosts_write').",
                        },
                        "description": {
                            "type": "string",
                            "description": "Full requirement description or rule specification.",
                        },
                        "strength": {
                            "type": "string",
                            "enum": ["HARD", "SOFT", "ASSUMPTION"],
                            "description": "Enforcement strength.",
                        },
                        "rule_effect": {
                            "type": "string",
                            "enum": ["DENY", "REQUIRE", "PREFER"],
                            "description": "Enforcement rule effect.",
                        },
                        "scope": {
                            "type": "object",
                            "properties": {
                                "target_type": {"type": ["string", "null"]},
                                "paths": {"type": "array", "items": {"type": "string"}},
                                "tools": {"type": "array", "items": {"type": "string"}},
                                "actions": {"type": "array", "items": {"type": "string"}},
                                "selectors": {"type": "object"},
                                "description": {"type": ["string", "null"]},
                            },
                        },
                        "compliance_scope": {
                            "type": "object",
                            "properties": {
                                "target_type": {"type": ["string", "null"]},
                                "paths": {"type": "array", "items": {"type": "string"}},
                                "tools": {"type": "array", "items": {"type": "string"}},
                                "actions": {"type": "array", "items": {"type": "string"}},
                                "selectors": {"type": "object"},
                                "description": {"type": ["string", "null"]},
                            },
                        },
                    },
                    "required": ["name", "description"],
                },
            }
        },
        "required": ["constraints"],
    }


def get_claim_extraction_schema() -> dict[str, Any]:
    """Return JSON Schema specifying expected claim extraction structured output."""
    return {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_type": {
                            "type": "string",
                            "enum": [
                                "TOOL_SUCCEEDED",
                                "COMMAND_EXITED_ZERO",
                                "TESTS_PASSED",
                                "FILE_EXISTS",
                                "ACTION_COMPLETED",
                                "GENERIC",
                            ],
                            "description": "Category of completion or state claim.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Atomic statement of what is claimed.",
                        },
                        "call_id": {"type": ["string", "null"]},
                        "tool_name": {"type": ["string", "null"]},
                        "command": {"type": ["string", "null"]},
                        "target_path": {"type": ["string", "null"]},
                        "expected_exit_code": {"type": ["integer", "null"]},
                    },
                    "required": ["claim_type", "description"],
                },
            }
        },
        "required": ["claims"],
    }
