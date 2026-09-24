"""Domain models for SpecGuard action validation, decisions, and observations."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints.models import ConstraintId
from agentcontract.guard.exceptions import GuardValidationError
from agentcontract.trace.models import (
    ToolCall,
    ToolResult,
    TraceDurableValue,
    TraceEvent,
    TracePointer,
    _freeze_trace_value,
)


class DecisionKind(StrEnum):
    """Enforcement decision produced by SpecGuard."""

    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"


class ActionKind(StrEnum):
    """Normalized category of an agent action."""

    TOOL_CALL = "TOOL_CALL"
    FILE_READ = "FILE_READ"
    FILE_WRITE = "FILE_WRITE"
    FILE_DELETE = "FILE_DELETE"
    COMMAND_EXEC = "COMMAND_EXEC"
    NETWORK_REQUEST = "NETWORK_REQUEST"
    STATE_CHANGE = "STATE_CHANGE"
    GENERIC = "GENERIC"


class Action(BaseModel):
    """A proposed or observed agent action to be evaluated against constraints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_kind: ActionKind = Field(
        default=ActionKind.GENERIC,
        description="Category of action (e.g. TOOL_CALL, FILE_WRITE, COMMAND_EXEC).",
    )
    target_type: str | None = Field(
        default=None,
        description="Category of target (e.g. 'filesystem', 'database', 'tool', 'network').",
    )
    target_path: str | None = Field(
        default=None,
        description="Primary target path or resource identifier.",
    )
    paths: tuple[str, ...] = Field(
        default_factory=tuple,
        description="All resource paths accessed or modified by this action.",
    )
    tool_name: str | None = Field(
        default=None,
        description="Tool name if this action invokes a tool.",
    )
    operation: str | None = Field(
        default=None,
        description="Specific verb or operation name (e.g. 'write', 'execute', 'delete').",
    )
    payload: TraceDurableValue = Field(
        default=None,
        description="Structured arguments, inputs, or parameters of the action.",
    )
    context: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Execution context or environment metadata for selector matching.",
    )
    trace_pointer: TracePointer | None = Field(
        default=None,
        description="Optional trace pointer linking this action to a trace event.",
    )

    @field_validator("target_type", "target_path", "tool_name", "operation", mode="before")
    @classmethod
    def _strip_optional_str(cls, val: Any) -> str | None:
        if val is None:
            return None
        if isinstance(val, str):
            stripped = val.strip()
            return stripped if stripped else None
        return str(val).strip() or None

    @field_validator("paths", mode="before")
    @classmethod
    def _normalize_paths(cls, val: Any) -> tuple[str, ...]:
        if val is None:
            return ()
        if isinstance(val, str):
            stripped = val.strip()
            return (stripped,) if stripped else ()
        if isinstance(val, (list, tuple, set, frozenset)):
            result = []
            for item in val:
                s = str(item).strip()
                if s:
                    result.append(s)
            return tuple(result)
        raise GuardValidationError(f"paths must be a sequence of strings, got {type(val).__name__}")

    @field_validator("context", mode="before")
    @classmethod
    def _freeze_context(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise GuardValidationError(f"context must be a mapping, got {type(val).__name__}")

    @field_validator("payload", mode="before")
    @classmethod
    def _freeze_action_payload(cls, val: Any) -> Any:
        return _freeze_trace_value(val)

    @model_validator(mode="after")
    def _sync_paths_and_kind(self) -> Self:
        # Default action_kind to TOOL_CALL if tool_name is provided and kind is GENERIC
        new_kind = self.action_kind
        if self.tool_name and self.action_kind == ActionKind.GENERIC:
            new_kind = ActionKind.TOOL_CALL

        # Synchronize target_path and paths
        new_paths = self.paths
        new_target_path = self.target_path
        if self.target_path and not self.paths:
            new_paths = (self.target_path,)
        elif self.paths and not self.target_path:
            new_target_path = self.paths[0]

        if new_kind != self.action_kind or new_paths != self.paths or new_target_path != self.target_path:
            object.__setattr__(self, "action_kind", new_kind)
            object.__setattr__(self, "paths", new_paths)
            object.__setattr__(self, "target_path", new_target_path)

        return self

    @classmethod
    def from_tool_call(
        cls,
        tool_call: ToolCall,
        action_kind: ActionKind = ActionKind.TOOL_CALL,
        target_path: str | None = None,
        paths: tuple[str, ...] | list[str] = (),
        target_type: str | None = None,
        operation: str | None = None,
        trace_pointer: TracePointer | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an Action from a validated ToolCall."""
        return cls(
            action_kind=action_kind,
            tool_name=tool_call.call_id if not tool_call.tool_name else tool_call.tool_name,
            target_path=target_path,
            paths=tuple(paths) if paths else ((target_path,) if target_path else ()),
            target_type=target_type,
            operation=operation,
            payload=tool_call.arguments,
            context=FrozenDict(context or {}),
            trace_pointer=trace_pointer,
        )

    @classmethod
    def from_trace_event(
        cls,
        event: TraceEvent,
        action_kind: ActionKind | None = None,
        target_path: str | None = None,
        paths: tuple[str, ...] | list[str] = (),
        target_type: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an Action from a TraceEvent (e.g. TOOL_CALL event)."""
        pointer = event.to_pointer()
        if event.tool_call:
            return cls.from_tool_call(
                tool_call=event.tool_call,
                action_kind=action_kind or ActionKind.TOOL_CALL,
                target_path=target_path,
                paths=paths,
                target_type=target_type,
                trace_pointer=pointer,
                context=context,
            )
        return cls(
            action_kind=action_kind or ActionKind.GENERIC,
            target_path=target_path,
            paths=tuple(paths) if paths else ((target_path,) if target_path else ()),
            target_type=target_type,
            payload=event.payload,
            context=FrozenDict(context or event.metadata),
            trace_pointer=pointer,
        )


class ActionObservation(BaseModel):
    """Observed runtime effects or outcomes of an executed action for post-validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str | None = Field(default=None, description="Actual tool executed.")
    action_kind: ActionKind | None = Field(default=None, description="Actual action kind.")
    changed_paths: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Resource paths modified during execution.",
    )
    accessed_paths: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Resource paths read or accessed during execution.",
    )
    target_type: str | None = Field(default=None, description="Actual target type.")
    output: TraceDurableValue = Field(
        default=None,
        description="Actual output or result payload.",
    )
    exit_code: int | None = Field(
        default=None,
        description="Process or tool exit code if applicable.",
    )
    context: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Observation context metadata.",
    )
    trace_pointer: TracePointer | None = Field(
        default=None,
        description="Optional trace pointer to the result event.",
    )

    @field_validator("changed_paths", "accessed_paths", mode="before")
    @classmethod
    def _normalize_paths(cls, val: Any) -> tuple[str, ...]:
        if val is None:
            return ()
        if isinstance(val, str):
            stripped = val.strip()
            return (stripped,) if stripped else ()
        if isinstance(val, (list, tuple, set, frozenset)):
            result = []
            for item in val:
                s = str(item).strip()
                if s:
                    result.append(s)
            return tuple(result)
        raise GuardValidationError(f"paths must be a sequence of strings, got {type(val).__name__}")

    @field_validator("output", mode="before")
    @classmethod
    def _freeze_obs_output(cls, val: Any) -> Any:
        return _freeze_trace_value(val)

    @field_validator("context", mode="before")
    @classmethod
    def _freeze_context(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise GuardValidationError(f"context must be a mapping, got {type(val).__name__}")

    @classmethod
    def from_tool_result(
        cls,
        tool_result: ToolResult,
        changed_paths: tuple[str, ...] | list[str] = (),
        accessed_paths: tuple[str, ...] | list[str] = (),
        tool_name: str | None = None,
        action_kind: ActionKind | None = None,
        trace_pointer: TracePointer | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an ActionObservation from a ToolResult."""
        return cls(
            tool_name=tool_name,
            action_kind=action_kind,
            changed_paths=tuple(changed_paths),
            accessed_paths=tuple(accessed_paths),
            output=tool_result.output,
            exit_code=tool_result.exit_code,
            context=FrozenDict(context or tool_result.metadata),
            trace_pointer=trace_pointer,
        )


class GuardDecision(BaseModel):
    """An immutable, serializable verdict produced by SpecGuard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: DecisionKind = Field(
        ...,
        description="Outcome of guard evaluation: ALLOW, WARN, or BLOCK.",
    )
    action: Action = Field(
        ...,
        description="The action that was evaluated.",
    )
    matched_constraint_ids: tuple[ConstraintId, ...] = Field(
        default_factory=tuple,
        description="IDs of all active constraints whose scope matched this action.",
    )
    violating_constraint_ids: tuple[ConstraintId, ...] = Field(
        default_factory=tuple,
        description="IDs of constraints that caused a BLOCK or WARN decision.",
    )
    reasons: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Human-readable deterministic explanations for the decision.",
    )
    trace_pointer: TracePointer | None = Field(
        default=None,
        description="Optional trace pointer linking to the action event.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Additional structured evaluation metadata.",
    )

    @field_validator("matched_constraint_ids", "violating_constraint_ids", "reasons", mode="before")
    @classmethod
    def _normalize_tuples(cls, val: Any) -> tuple[Any, ...]:
        if val is None:
            return ()
        if isinstance(val, (list, tuple, set, frozenset)):
            return tuple(val)
        return (val,)

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise GuardValidationError(f"metadata must be a mapping, got {type(val).__name__}")

    @property
    def is_allowed(self) -> bool:
        """True if the action was allowed without blocking."""
        return self.decision == DecisionKind.ALLOW

    @property
    def is_warned(self) -> bool:
        """True if the action produced a warning."""
        return self.decision == DecisionKind.WARN

    @property
    def is_blocked(self) -> bool:
        """True if the action was blocked."""
        return self.decision == DecisionKind.BLOCK

    @property
    def reason(self) -> str:
        """Consolidated reason string."""
        return "; ".join(self.reasons) if self.reasons else "Action allowed."

    @property
    def constraint_ids(self) -> tuple[ConstraintId, ...]:
        """Convenience alias for matched_constraint_ids."""
        return self.matched_constraint_ids
