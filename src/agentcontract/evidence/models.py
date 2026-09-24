"""Domain models for agent claims, evidence references, and deterministic evaluations."""

from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict
from agentcontract.evidence.exceptions import EvidenceValidationError
from agentcontract.trace.models import EventKind, TraceEvent, TracePointer, _freeze_trace_value


class ClaimType(StrEnum):
    """Classification of verifiable agent completion or state claims."""

    TOOL_SUCCEEDED = "TOOL_SUCCEEDED"
    COMMAND_EXITED_ZERO = "COMMAND_EXITED_ZERO"
    TESTS_PASSED = "TESTS_PASSED"
    FILE_EXISTS = "FILE_EXISTS"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    GENERIC = "GENERIC"


class ClaimVerdict(StrEnum):
    """Deterministic evaluation verdict for a claim against trace evidence."""

    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"


class EvidenceRelation(StrEnum):
    """Relationship between an evidence item and a claim."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"


class EvidenceRef(BaseModel):
    """An immutable reference to a specific trace event serving as evidence for a claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_pointer: TracePointer = Field(..., description="Durable pointer to the exact trace event.")
    relation: EvidenceRelation = Field(
        default=EvidenceRelation.SUPPORTS,
        description="Whether this evidence supports or contradicts the claim.",
    )
    call_id: str | None = Field(
        default=None,
        description="Optional tool call identifier associated with this evidence.",
    )
    event_kind: EventKind | None = Field(
        default=None,
        description="Optional event kind of the referenced event.",
    )
    reason: str | None = Field(
        default=None,
        description="Explanation of how this event supports or contradicts the claim.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Additional structured evidence attributes.",
    )

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise EvidenceValidationError(f"metadata must be a mapping, got {type(val).__name__}")

    @property
    def trace_id(self) -> str:
        """Trace identifier containing the evidence event."""
        return self.trace_pointer.trace_id

    @property
    def event_id(self) -> str:
        """Exact event identifier of the evidence."""
        return self.trace_pointer.event_id

    @property
    def session_id(self) -> str | None:
        """Optional session identifier containing the evidence."""
        return self.trace_pointer.session_id

    @classmethod
    def from_event(
        cls,
        event: TraceEvent,
        relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
        reason: str | None = None,
        call_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an EvidenceRef pointing directly to a TraceEvent."""
        derived_call_id = call_id
        if derived_call_id is None:
            if event.tool_call is not None:
                derived_call_id = event.tool_call.call_id
            elif event.tool_result is not None:
                derived_call_id = event.tool_result.call_id

        return cls(
            trace_pointer=event.to_pointer(),
            relation=relation,
            call_id=derived_call_id,
            event_kind=event.event_kind,
            reason=reason,
            metadata=FrozenDict(metadata or {}),
        )


class Claim(BaseModel):
    """An atomic, structured completion or state claim asserted by an agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(..., description="Unique stable identifier for this claim.")
    claim_type: ClaimType = Field(..., description="Category of the claim.")
    description: str = Field(..., description="Human-readable statement of what is claimed.")
    trace_id: str | None = Field(
        default=None,
        description="Optional trace ID scoping this claim.",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session ID scoping this claim.",
    )
    call_id: str | None = Field(
        default=None,
        description="Optional tool call ID this claim directly refers to.",
    )
    tool_name: str | None = Field(
        default=None,
        description="Optional tool name expected to have executed.",
    )
    command: str | None = Field(
        default=None,
        description="Optional command string expected to have executed.",
    )
    target_path: str | None = Field(
        default=None,
        description="Optional target file or resource path claimed to exist or have been modified.",
    )
    expected_exit_code: int | None = Field(
        default=None,
        description="Optional expected process exit code (e.g. 0).",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Immutable metadata and custom attributes.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timezone-aware UTC timestamp when this claim was created.",
    )

    @field_validator("claim_id", "description")
    @classmethod
    def _validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise EvidenceValidationError("Identifier and description must not be empty or blank.")
        return stripped

    @field_validator("created_at")
    @classmethod
    def _validate_timestamp(cls, dt: datetime) -> datetime:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise EvidenceValidationError("Claim timestamp must be timezone-aware (tzinfo is required).")
        return dt.astimezone(timezone.utc)

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise EvidenceValidationError(f"Claim metadata must be a mapping, got {type(val).__name__}")


class ClaimEvaluation(BaseModel):
    """The deterministic evaluation verdict and provenance for a claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: Claim = Field(..., description="The claim evaluated.")
    verdict: ClaimVerdict = Field(..., description="Outcome: VERIFIED, CONTRADICTED, or UNVERIFIED.")
    supporting_evidence: tuple[EvidenceRef, ...] = Field(
        default_factory=tuple,
        description="Evidence references supporting this claim in deterministic order.",
    )
    contradicting_evidence: tuple[EvidenceRef, ...] = Field(
        default_factory=tuple,
        description="Evidence references contradicting this claim in deterministic order.",
    )
    reason: str = Field(..., description="Deterministic explanation for the verdict.")
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timezone-aware UTC timestamp when evaluation occurred.",
    )

    @field_validator("evaluated_at")
    @classmethod
    def _validate_timestamp(cls, dt: datetime) -> datetime:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise EvidenceValidationError("evaluated_at must be timezone-aware (tzinfo is required).")
        return dt.astimezone(timezone.utc)

    @field_validator("supporting_evidence", "contradicting_evidence", mode="before")
    @classmethod
    def _normalize_evidence_tuple(cls, val: Any) -> tuple[EvidenceRef, ...]:
        if val is None:
            return ()
        if isinstance(val, (set, frozenset)):
            raise EvidenceValidationError("Evidence sequence must be an ordered list or tuple, not a set/frozenset.")
        if isinstance(val, (list, tuple)):
            return tuple(val)
        raise EvidenceValidationError(f"Expected sequence of EvidenceRef, got {type(val).__name__}")

    @property
    def is_verified(self) -> bool:
        """True if the claim was verified by matching trace evidence."""
        return self.verdict == ClaimVerdict.VERIFIED

    @property
    def is_contradicted(self) -> bool:
        """True if the claim was contradicted by trace evidence."""
        return self.verdict == ClaimVerdict.CONTRADICTED

    @property
    def is_unverified(self) -> bool:
        """True if the claim lacks sufficient evidence to verify or contradict."""
        return self.verdict == ClaimVerdict.UNVERIFIED

    @property
    def evidence_refs(self) -> tuple[EvidenceRef, ...]:
        """All evidence references associated with this evaluation."""
        return self.supporting_evidence + self.contradicting_evidence
