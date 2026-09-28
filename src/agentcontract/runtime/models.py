"""Domain models for runtime execution outcomes, wrapper results, and verification."""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict
from agentcontract.evidence.models import ClaimEvaluation
from agentcontract.guard.models import Action, ActionKind, DecisionKind, GuardDecision
from agentcontract.runtime.exceptions import RuntimeValidationError
from agentcontract.trace.models import (
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceDurableValue,
    TracePointer,
    _freeze_trace_value,
)


class ToolExecutionOutcome(BaseModel):
    """Normalized structured outcome returned by or extracted from a tool executor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ToolResultStatus = Field(
        default=ToolResultStatus.SUCCESS,
        description="Tool execution outcome status.",
    )
    output: TraceDurableValue = Field(
        default=None,
        description="Structured or scalar tool output payload.",
    )
    error: str | None = Field(
        default=None,
        description="Error details if tool execution failed or was interrupted.",
    )
    exit_code: int | None = Field(
        default=None,
        description="Optional process exit code or status code.",
    )
    duration_ms: float | None = Field(
        default=None,
        ge=0,
        description="Execution duration in milliseconds.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Additional execution metadata.",
    )
    changed_paths: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Observed resource paths modified during execution.",
    )
    accessed_paths: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Observed resource paths read or accessed during execution.",
    )
    action_kind: ActionKind | None = Field(
        default=None,
        description="Actual action category if refined during execution.",
    )
    target_type: str | None = Field(
        default=None,
        description="Actual target resource type.",
    )
    tool_name: str | None = Field(
        default=None,
        description="Actual tool name executed.",
    )

    @field_validator("changed_paths", "accessed_paths", mode="before")
    @classmethod
    def _normalize_paths(cls, val: Any) -> tuple[str, ...]:
        if val is None:
            return ()
        if isinstance(val, str):
            stripped = val.strip()
            return (stripped,) if stripped else ()
        if isinstance(val, (set, frozenset)):
            raise RuntimeValidationError("paths must be an ordered sequence (list or tuple), not a set/frozenset.")
        if isinstance(val, (list, tuple)):
            result = []
            for item in val:
                s = str(item).strip()
                if s:
                    result.append(s)
            return tuple(result)
        raise RuntimeValidationError(f"paths must be a sequence of strings, got {type(val).__name__}")

    @field_validator("output", mode="before")
    @classmethod
    def _freeze_outcome_output(cls, val: Any) -> Any:
        return _freeze_trace_value(val)

    @field_serializer("output", mode="plain")
    def _serialize_output(self, val: Any) -> Any:
        def _to_serializable(v: Any) -> Any:
            if isinstance(v, FrozenDict):
                return {str(k): _to_serializable(item) for k, item in v.items()}
            if isinstance(v, tuple):
                return [_to_serializable(item) for item in v]
            return v

        return _to_serializable(val)

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise RuntimeValidationError(f"metadata must be a mapping, got {type(val).__name__}")

    @classmethod
    def success(
        cls,
        output: Any = None,
        *,
        changed_paths: Sequence[str] | Any = (),
        accessed_paths: Sequence[str] | Any = (),
        exit_code: int = 0,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        """Create a successful execution outcome."""
        return cls(
            status=ToolResultStatus.SUCCESS,
            output=output,
            exit_code=exit_code,
            changed_paths=changed_paths,
            accessed_paths=accessed_paths,
            duration_ms=duration_ms,
            metadata=FrozenDict(metadata or {}),
            **kwargs,
        )

    @classmethod
    def failed(
        cls,
        error: str,
        *,
        exit_code: int = 1,
        output: Any = None,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        """Create a failed execution outcome with an error message."""
        return cls(
            status=ToolResultStatus.ERROR,
            error=error,
            exit_code=exit_code,
            output=output,
            duration_ms=duration_ms,
            metadata=FrozenDict(metadata or {}),
            **kwargs,
        )

    @classmethod
    def create_error(
        cls,
        error: str,
        *,
        exit_code: int = 1,
        output: Any = None,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        """Alias for failed()."""
        return cls.failed(
            error=error,
            exit_code=exit_code,
            output=output,
            duration_ms=duration_ms,
            metadata=metadata,
            **kwargs,
        )


    @classmethod
    def timeout(
        cls,
        error: str = "Tool execution timed out",
        *,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        """Create a timed out execution outcome."""
        return cls(
            status=ToolResultStatus.TIMEOUT,
            error=error,
            duration_ms=duration_ms,
            metadata=FrozenDict(metadata or {}),
            **kwargs,
        )

    @classmethod
    def cancelled(
        cls,
        error: str = "Tool execution was cancelled",
        *,
        duration_ms: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        """Create a cancelled execution outcome."""
        return cls(
            status=ToolResultStatus.CANCELLED,
            error=error,
            duration_ms=duration_ms,
            metadata=FrozenDict(metadata or {}),
            **kwargs,
        )

    @classmethod
    def from_tool_result(
        cls,
        tool_result: ToolResult,
        *,
        changed_paths: Sequence[str] | Any = (),
        accessed_paths: Sequence[str] | Any = (),
        action_kind: ActionKind | None = None,
        target_type: str | None = None,
        tool_name: str | None = None,
    ) -> Self:
        """Create a ToolExecutionOutcome from an existing ToolResult."""
        return cls(
            status=tool_result.status,
            output=tool_result.output,
            error=tool_result.error,
            exit_code=tool_result.exit_code,
            duration_ms=tool_result.duration_ms,
            metadata=tool_result.metadata,
            changed_paths=changed_paths,
            accessed_paths=accessed_paths,
            action_kind=action_kind,
            target_type=target_type,
            tool_name=tool_name,
        )


@runtime_checkable
class ToolExecutor(Protocol):
    """Protocol for vendor-neutral tool execution callables."""

    def __call__(self, action: Action, tool_call: ToolCall) -> Any:
        """Execute a tool for a given action and tool call."""
        ...


class RuntimeExecutionResult(BaseModel):
    """Aggregated outcome of an action evaluated and optionally executed by the runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Action = Field(..., description="Proposed agent action.")
    pre_decision: GuardDecision = Field(..., description="Pre-action SpecGuard validation decision.")
    executed: bool = Field(..., description="Whether tool execution occurred.")
    tool_call: ToolCall | None = Field(
        default=None,
        description="Correlated ToolCall model if execution took place.",
    )
    tool_result: ToolResult | None = Field(
        default=None,
        description="Correlated ToolResult model if execution took place.",
    )
    post_decision: GuardDecision | None = Field(
        default=None,
        description="Post-action SpecGuard validation decision if execution took place.",
    )
    pre_guard_event_pointer: TracePointer | None = Field(
        default=None,
        description="Pointer to pre-action guard event in trace if recorded.",
    )
    tool_call_event_pointer: TracePointer | None = Field(
        default=None,
        description="Pointer to TOOL_CALL trace event if executed.",
    )
    tool_result_event_pointer: TracePointer | None = Field(
        default=None,
        description="Pointer to TOOL_RESULT trace event if executed.",
    )
    post_guard_event_pointer: TracePointer | None = Field(
        default=None,
        description="Pointer to post-action guard event in trace if recorded.",
    )

    @property
    def is_blocked(self) -> bool:
        """True if the action was blocked before execution."""
        return self.pre_decision.is_blocked

    @property
    def is_post_blocked(self) -> bool:
        """True if the action violated constraints observed during post-action validation."""
        return self.post_decision is not None and self.post_decision.is_blocked

    @property
    def is_warned(self) -> bool:
        """True if either pre-action or post-action evaluation triggered a warning."""
        pre_warn = self.pre_decision.is_warned
        post_warn = self.post_decision is not None and self.post_decision.is_warned
        return pre_warn or post_warn

    @property
    def is_allowed(self) -> bool:
        """True if the action was allowed pre-action without blocking."""
        return self.pre_decision.is_allowed

    @property
    def is_success(self) -> bool:
        """True if the tool executed successfully and was not blocked by post-action guard."""
        if not self.executed or self.tool_result is None:
            return False
        if not self.tool_result.is_success:
            return False
        if self.post_decision is not None and self.post_decision.is_blocked:
            return False
        return True

    @property
    def trace_pointers(self) -> tuple[TracePointer, ...]:
        """All trace pointers associated with this execution result in encounter order."""
        pointers: list[TracePointer] = []
        for p in (
            self.pre_guard_event_pointer,
            self.tool_call_event_pointer,
            self.tool_result_event_pointer,
            self.post_guard_event_pointer,
        ):
            if p is not None:
                pointers.append(p)
        return tuple(pointers)


class VerificationResult(BaseModel):
    """Aggregated completion claim evaluations produced by EvidenceGate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluations: tuple[ClaimEvaluation, ...] = Field(
        default_factory=tuple,
        description="Ordered sequence of claim evaluations.",
    )

    @field_validator("evaluations", mode="before")
    @classmethod
    def _normalize_evaluations(cls, val: Any) -> tuple[ClaimEvaluation, ...]:
        if val is None:
            return ()
        if isinstance(val, (set, frozenset)):
            raise RuntimeValidationError("evaluations must be an ordered sequence (list or tuple), not a set/frozenset.")
        if isinstance(val, (list, tuple)):
            return tuple(val)
        raise RuntimeValidationError(f"Expected sequence of ClaimEvaluation, got {type(val).__name__}")

    def __iter__(self) -> Iterator[ClaimEvaluation]:
        return iter(self.evaluations)

    def __len__(self) -> int:
        return len(self.evaluations)

    def __getitem__(self, index: int | slice) -> Any:
        return self.evaluations[index]

    @property
    def all_verified(self) -> bool:
        """True if at least one claim was evaluated and all evaluations are VERIFIED."""
        return bool(self.evaluations) and all(e.is_verified for e in self.evaluations)

    @property
    def has_contradictions(self) -> bool:
        """True if any evaluated claim was CONTRADICTED."""
        return any(e.is_contradicted for e in self.evaluations)

    @property
    def has_unverified(self) -> bool:
        """True if any evaluated claim is UNVERIFIED."""
        return any(e.is_unverified for e in self.evaluations)

    @property
    def by_claim_id(self) -> FrozenDict:
        """Mapping from claim_id to its ClaimEvaluation."""
        return FrozenDict({e.claim.claim_id: e for e in self.evaluations})

    def get(self, claim_id: str) -> ClaimEvaluation | None:
        """Retrieve evaluation for a specific claim_id or None if not present."""
        return self.by_claim_id.get(claim_id)


class IdGenerator:
    """Configurable identifier generator for traces, sessions, events, and calls."""

    def __init__(self, prefix: str = "", deterministic: bool = False) -> None:
        self._prefix = prefix
        self._deterministic = deterministic
        self._counters: dict[str, int] = {}

    def new_id(self, category: str = "id") -> str:
        """Generate a new unique identifier."""
        cnt = self._counters.get(category, 0) + 1
        self._counters[category] = cnt
        if self._deterministic:
            base = f"{category}_{cnt:04d}"
        else:
            base = f"{category}_{uuid.uuid4().hex[:12]}"
        return f"{self._prefix}{base}" if self._prefix else base

    def new_event_id(self) -> str:
        """Generate a new event identifier."""
        return self.new_id("evt")

    def new_call_id(self) -> str:
        """Generate a new tool call identifier."""
        return self.new_id("call")

    def new_trace_id(self) -> str:
        """Generate a new trace identifier."""
        return self.new_id("trace")

    def new_session_id(self) -> str:
        """Generate a new session identifier."""
        return self.new_id("session")
