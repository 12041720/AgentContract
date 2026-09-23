"""Core domain models for the vendor-neutral trace and provenance subsystem."""

from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, TypeAlias
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict, _freeze_value
from agentcontract.trace.exceptions import (
    InvalidSequenceError,
    TraceValidationError,
)

# Strongly-typed identifier aliases
TraceId: TypeAlias = str
SessionId: TypeAlias = str
EventId: TypeAlias = str
ToolCallId: TypeAlias = str


def _freeze_trace_value(val: Any) -> Any:
    """Recursively validate and freeze trace values into an immutable, JSON-compatible domain.

    Permitted types:
    - None
    - bool
    - int (excluding bool)
    - float
    - str
    - Mapping (recursively frozen into FrozenDict)
    - list, tuple (recursively frozen into tuple)
    - set, frozenset (recursively frozen into frozenset)

    Any other type (e.g. bytearray, bytes, custom classes, mutable containers) is rejected
    with TraceValidationError.
    """
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, FrozenDict):
        return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
    if isinstance(val, Mapping):
        return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
    if isinstance(val, (list, tuple)):
        return tuple(_freeze_trace_value(v) for v in val)
    if isinstance(val, (set, frozenset)):
        return frozenset(_freeze_trace_value(v) for v in val)
    raise TraceValidationError(
        f"Unsupported trace value of type '{type(val).__name__}': trace values must be "
        f"scalars (None, bool, int, float, str) or composed of mappings/sequences thereof."
    )


class ActorKind(StrEnum):
    """Normalized classification of entities producing trace events."""

    USER = "USER"
    AGENT = "AGENT"
    TOOL = "TOOL"
    SYSTEM = "SYSTEM"
    GUARD = "GUARD"
    ENVIRONMENT = "ENVIRONMENT"


class EventKind(StrEnum):
    """Normalized classification of trace events."""

    USER_MESSAGE = "USER_MESSAGE"
    AGENT_MESSAGE = "AGENT_MESSAGE"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    GUARD_DECISION = "GUARD_DECISION"
    STATE_OBSERVATION = "STATE_OBSERVATION"
    ERROR = "ERROR"


class ToolResultStatus(StrEnum):
    """Outcome status of a tool invocation."""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class TracePointer(BaseModel):
    """A compact, durable provenance reference pointing to an exact event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: TraceId = Field(..., description="Target trace identifier.")
    event_id: EventId = Field(..., description="Target event identifier within the trace.")
    session_id: SessionId | None = Field(
        default=None,
        description="Optional session identifier.",
    )

    @field_validator("trace_id", "event_id", "session_id")
    @classmethod
    def _validate_non_empty(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise TraceValidationError("Identifier must not be empty or blank.")
        return stripped


class ToolCall(BaseModel):
    """A proposed or executed tool call invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: ToolCallId = Field(..., description="Stable unique tool call identifier.")
    tool_name: str = Field(..., description="Target tool name.")
    arguments: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Immutable structured tool arguments.",
    )

    @field_validator("call_id", "tool_name")
    @classmethod
    def _validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise TraceValidationError("call_id and tool_name must not be empty or blank.")
        return stripped

    @field_validator("arguments", mode="before")
    @classmethod
    def _freeze_arguments(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise TraceValidationError(f"ToolCall arguments must be a mapping, got {type(val).__name__}")


class ToolResult(BaseModel):
    """The normalized outcome of a tool execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: ToolCallId = Field(..., description="Matching tool call identifier.")
    status: ToolResultStatus = Field(..., description="Tool execution outcome status.")
    output: Any | None = Field(
        default=None,
        description="Immutable structured or raw tool output.",
    )
    error: str | None = Field(
        default=None,
        description="Optional error message or error details.",
    )
    exit_code: int | None = Field(
        default=None,
        description="Optional process exit code or status code.",
    )
    duration_ms: float | None = Field(
        default=None,
        ge=0,
        description="Optional execution duration in milliseconds.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Additional execution metadata.",
    )

    @field_validator("call_id")
    @classmethod
    def _validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise TraceValidationError("call_id must not be empty or blank.")
        return stripped

    @field_validator("output", mode="after")
    @classmethod
    def _freeze_output(cls, val: Any) -> Any:
        return _freeze_trace_value(val)

    @field_serializer("output", mode="plain")
    def _serialize_output(self, val: Any) -> Any:
        def _to_serializable(v: Any) -> Any:
            if isinstance(v, FrozenDict):
                return {str(k): _to_serializable(item) for k, item in v.items()}
            if isinstance(v, (list, tuple)):
                return [_to_serializable(item) for item in v]
            if isinstance(v, (set, frozenset)):
                return [_to_serializable(item) for item in sorted(v, key=lambda x: str(x))]
            return v

        return _to_serializable(val)

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise TraceValidationError(f"ToolResult metadata must be a mapping, got {type(val).__name__}")

    @property
    def is_success(self) -> bool:
        """True if the tool executed successfully."""
        return self.status == ToolResultStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        """True if the tool failed with an error."""
        return self.status == ToolResultStatus.ERROR

    @property
    def is_timeout(self) -> bool:
        """True if the tool timed out."""
        return self.status == ToolResultStatus.TIMEOUT

    @property
    def is_cancelled(self) -> bool:
        """True if the tool execution was cancelled."""
        return self.status == ToolResultStatus.CANCELLED


class TraceEvent(BaseModel):
    """An immutable, append-oriented record of an agent, tool, or system event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: EventId = Field(..., description="Unique event identifier.")
    trace_id: TraceId = Field(..., description="Trace identifier grouping events.")
    session_id: SessionId | None = Field(
        default=None,
        description="Optional session identifier.",
    )
    sequence: int = Field(
        ...,
        ge=0,
        description="Monotonically increasing sequence within the trace.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timezone-aware UTC timestamp of the event.",
    )
    actor: ActorKind = Field(..., description="Entity producing the event.")
    event_kind: EventKind = Field(..., description="Classification of the event.")
    parent_id: EventId | None = Field(
        default=None,
        description="Optional parent event identifier in the same trace.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Immutable event attributes and metadata.",
    )
    payload: ToolCall | ToolResult | FrozenDict | str | None = Field(
        default=None,
        description="Durable structured or text payload.",
    )

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, dt: datetime) -> datetime:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise TraceValidationError("Event timestamp must be timezone-aware (tzinfo is required).")
        return dt.astimezone(timezone.utc)

    @field_validator("metadata", mode="before")
    @classmethod
    def _freeze_metadata(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            return FrozenDict({str(k): _freeze_trace_value(v) for k, v in val.items()})
        raise TraceValidationError(f"metadata must be a mapping, got {type(val).__name__}")

    @field_serializer("payload", mode="plain")
    def _serialize_payload(self, val: Any) -> Any:
        if isinstance(val, BaseModel):
            return val.model_dump(mode="json")
        def _to_serializable(v: Any) -> Any:
            if isinstance(v, FrozenDict):
                return {str(k): _to_serializable(item) for k, item in v.items()}
            if isinstance(v, (list, tuple)):
                return [_to_serializable(item) for item in v]
            if isinstance(v, (set, frozenset)):
                return [_to_serializable(item) for item in sorted(v, key=lambda x: str(x))]
            return v
        return _to_serializable(val)

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        event_kind = data.get("event_kind")
        payload = data.get("payload")

        if event_kind in (EventKind.TOOL_CALL, "TOOL_CALL"):
            if isinstance(payload, dict) and not isinstance(payload, ToolCall):
                data["payload"] = ToolCall.model_validate(payload)
        elif event_kind in (EventKind.TOOL_RESULT, "TOOL_RESULT"):
            if isinstance(payload, dict) and not isinstance(payload, ToolResult):
                data["payload"] = ToolResult.model_validate(payload)
        elif isinstance(payload, Mapping) and not isinstance(payload, FrozenDict):
            data["payload"] = FrozenDict({str(k): _freeze_trace_value(v) for k, v in payload.items()})
        elif isinstance(payload, (list, tuple)):
            data["payload"] = tuple(_freeze_trace_value(v) for v in payload)
        elif isinstance(payload, (set, frozenset)):
            data["payload"] = frozenset(_freeze_trace_value(v) for v in payload)
        elif payload is not None and not isinstance(payload, (ToolCall, ToolResult, FrozenDict)):
            data["payload"] = _freeze_trace_value(payload)

        return data

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        # Non-empty identifier validations
        if not self.event_id or not self.event_id.strip():
            raise TraceValidationError("event_id must not be empty or blank.")
        if not self.trace_id or not self.trace_id.strip():
            raise TraceValidationError("trace_id must not be empty or blank.")
        if self.parent_id is not None and not self.parent_id.strip():
            raise TraceValidationError("parent_id when provided must not be empty or blank.")
        if self.session_id is not None and not self.session_id.strip():
            raise TraceValidationError("session_id when provided must not be empty or blank.")

        if self.sequence < 0:
            raise InvalidSequenceError(f"sequence must be non-negative, got {self.sequence}")

        # Invariant: TOOL_CALL requires ToolCall payload
        if self.event_kind == EventKind.TOOL_CALL:
            if not isinstance(self.payload, ToolCall):
                raise TraceValidationError(
                    f"TOOL_CALL event requires ToolCall payload, got {type(self.payload)}"
                )

        # Invariant: TOOL_RESULT requires ToolResult payload
        if self.event_kind == EventKind.TOOL_RESULT:
            if not isinstance(self.payload, ToolResult):
                raise TraceValidationError(
                    f"TOOL_RESULT event requires ToolResult payload, got {type(self.payload)}"
                )

        return self

    @property
    def tool_call(self) -> ToolCall | None:
        """Return the ToolCall payload if this is a TOOL_CALL event, else None."""
        return self.payload if isinstance(self.payload, ToolCall) else None

    @property
    def tool_result(self) -> ToolResult | None:
        """Return the ToolResult payload if this is a TOOL_RESULT event, else None."""
        return self.payload if isinstance(self.payload, ToolResult) else None

    def to_pointer(self) -> TracePointer:
        """Create a compact TracePointer targeting this event."""
        return TracePointer(
            trace_id=self.trace_id,
            event_id=self.event_id,
            session_id=self.session_id,
        )
