"""OpenTelemetry-compatible trace export bridge and span models."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict
from agentcontract.guard.models import DecisionKind, GuardDecision
from agentcontract.runtime.models import RuntimeExecutionResult
from agentcontract.trace.models import (
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
)
from agentcontract.trace.store import TraceStore


def to_otlp_trace_id(raw_id: str) -> str:
    """Deterministically convert an arbitrary AgentContract trace identifier into a 32-hex OTLP trace ID.

    If raw_id is already a valid non-zero 32-hex string, it is normalized to lowercase.
    Otherwise, a stable SHA-256 hash prefix is used to produce a valid 32-hex string.
    The resulting ID is guaranteed to be non-zero and match ^[0-9a-f]{32}$.
    """
    cleaned = raw_id.strip()
    if len(cleaned) == 32 and re.fullmatch(r"^[0-9a-fA-F]{32}$", cleaned) and cleaned != "0" * 32:
        return cleaned.lower()
    hashed = hashlib.sha256(f"agentcontract:trace:{cleaned}".encode("utf-8")).hexdigest()[:32]
    if hashed == "0" * 32:
        return "1" + "0" * 31
    return hashed


def to_otlp_span_id(raw_id: str) -> str:
    """Deterministically convert an arbitrary AgentContract event identifier into a 16-hex OTLP span ID.

    If raw_id is already a valid non-zero 16-hex string, it is normalized to lowercase.
    Otherwise, a stable SHA-256 hash prefix is used to produce a valid 16-hex string.
    The resulting ID is guaranteed to be non-zero and match ^[0-9a-f]{16}$.
    """
    cleaned = raw_id.strip()
    if len(cleaned) == 16 and re.fullmatch(r"^[0-9a-fA-F]{16}$", cleaned) and cleaned != "0" * 16:
        return cleaned.lower()
    hashed = hashlib.sha256(f"agentcontract:event:{cleaned}".encode("utf-8")).hexdigest()[:16]
    if hashed == "0" * 16:
        return "1" + "0" * 15
    return hashed


def _to_unix_nano(dt: datetime) -> int:
    """Convert timezone-aware datetime to unix nanoseconds."""
    utc_dt = dt.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = utc_dt - epoch
    return int(delta.total_seconds() * 1_000_000_000)


def _serialize_attribute_value(val: Any) -> bool | int | float | str | list[Any]:
    """Serialize arbitrary values into OpenTelemetry attribute-compatible primitives."""
    if isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, (list, tuple)):
        return [_serialize_attribute_value(item) for item in val]
    if isinstance(val, Mapping):
        return json.dumps({str(k): val[k] for k in sorted(val.keys())}, default=str)
    return str(val)


class OTelSpan(BaseModel):
    """An immutable OpenTelemetry-compatible span representation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Span operation name.")
    trace_id: str = Field(..., description="Correlated trace identifier (preserved as-is).")
    span_id: str = Field(..., description="Unique span identifier (preserves event_id or call_id).")
    parent_span_id: str | None = Field(
        default=None,
        description="Correlated parent span identifier.",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional correlated session identifier.",
    )
    otlp_trace_id: str = Field(
        default="",
        description="Standard 32-hex character OpenTelemetry trace ID.",
    )
    otlp_span_id: str = Field(
        default="",
        description="Standard 16-hex character OpenTelemetry span ID.",
    )
    otlp_parent_span_id: str | None = Field(
        default=None,
        description="Standard 16-hex character OpenTelemetry parent span ID.",
    )
    start_time_unix_nano: int = Field(..., ge=0, description="Start timestamp in unix nanoseconds.")
    end_time_unix_nano: int = Field(..., ge=0, description="End timestamp in unix nanoseconds.")
    status_code: str = Field(
        default="OK",
        description="OpenTelemetry span status code ('OK', 'ERROR', 'UNSET').",
    )
    status_description: str | None = Field(
        default=None,
        description="Optional status description or error details.",
    )
    attributes: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Deterministic, key-sorted span attributes.",
    )
    events: tuple[FrozenDict, ...] = Field(
        default_factory=tuple,
        description="Span event annotations.",
    )
    resource_attributes: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Resource-level attributes.",
    )

    @field_validator("attributes", "resource_attributes", mode="before")
    @classmethod
    def _freeze_sorted_attributes(cls, val: Any) -> FrozenDict:
        if val is None:
            return FrozenDict()
        if isinstance(val, Mapping):
            # Sort keys deterministically
            sorted_dict = {
                str(k): _serialize_attribute_value(val[k])
                for k in sorted(val.keys())
            }
            return FrozenDict(sorted_dict)
        return FrozenDict()

    @field_validator("events", mode="before")
    @classmethod
    def _freeze_events(cls, val: Any) -> tuple[FrozenDict, ...]:
        if val is None:
            return ()
        if isinstance(val, (list, tuple)):
            result = []
            for item in val:
                if isinstance(item, Mapping):
                    result.append(FrozenDict({str(k): item[k] for k in sorted(item.keys())}))
            return tuple(result)
        return ()

    @model_validator(mode="after")
    def _populate_otlp_wire_ids(self) -> Self:
        if not self.otlp_trace_id:
            object.__setattr__(self, "otlp_trace_id", to_otlp_trace_id(self.trace_id))
        if not self.otlp_span_id:
            object.__setattr__(self, "otlp_span_id", to_otlp_span_id(self.span_id))
        if self.parent_span_id and not self.otlp_parent_span_id:
            object.__setattr__(self, "otlp_parent_span_id", to_otlp_span_id(self.parent_span_id))
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert span to a JSON-serializable dictionary."""
        return self.model_dump(mode="json")


class OTelTraceExport(BaseModel):
    """Container holding OpenTelemetry spans exported from an AgentContract trace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(..., description="Exported trace identifier.")
    session_id: str | None = Field(default=None, description="Correlated session identifier.")
    spans: tuple[OTelSpan, ...] = Field(default_factory=tuple, description="Exported spans.")
    resource_attributes: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Resource attributes applied to the trace export.",
    )

    def to_otlp_dict(self) -> dict[str, Any]:
        """Convert to standard OpenTelemetry OTLP JSON dictionary representation."""
        resource_attrs_list = [
            {"key": str(k), "value": {"stringValue": str(v)}}
            for k, v in sorted(self.resource_attributes.items())
        ]

        scope_spans: list[dict[str, Any]] = []
        for span in self.spans:
            span_attrs = []
            for k, v in sorted(span.attributes.items()):
                if isinstance(v, bool):
                    val_obj = {"boolValue": v}
                elif isinstance(v, int):
                    val_obj = {"intValue": str(v)}
                elif isinstance(v, float):
                    val_obj = {"doubleValue": v}
                elif isinstance(v, list):
                    val_obj = {"arrayValue": {"values": [{"stringValue": str(x)} for x in v]}}
                else:
                    val_obj = {"stringValue": str(v)}
                span_attrs.append({"key": str(k), "value": val_obj})

            span_dict = {
                "traceId": span.otlp_trace_id,
                "spanId": span.otlp_span_id,
                "parentSpanId": span.otlp_parent_span_id or "",
                "name": span.name,
                "kind": 1,  # SPAN_KIND_INTERNAL
                "startTimeUnixNano": str(span.start_time_unix_nano),
                "endTimeUnixNano": str(span.end_time_unix_nano),
                "attributes": span_attrs,
                "status": {
                    "code": 2 if span.status_code == "ERROR" else (1 if span.status_code == "OK" else 0),
                    "message": span.status_description or "",
                },
            }
            scope_spans.append(span_dict)

        return {
            "resourceSpans": [
                {
                    "resource": {"attributes": resource_attrs_list},
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "agentcontract",
                                "version": "0.1.0",
                            },
                            "spans": scope_spans,
                        }
                    ],
                }
            ]
        }


class OTelTraceBridge:
    """Bridge mapping AgentContract traces and events to OpenTelemetry spans."""

    DEFAULT_RESOURCE_ATTRIBUTES: Mapping[str, str] = {
        "service.name": "agentcontract",
        "telemetry.sdk.name": "agentcontract-otel",
        "telemetry.sdk.language": "python",
        "agentcontract.version": "0.1.0",
    }

    @classmethod
    def export_event(
        cls,
        event: TraceEvent,
        *,
        resource_attributes: Mapping[str, Any] | None = None,
    ) -> OTelSpan:
        """Map a single TraceEvent into an OpenTelemetry-compatible span.

        Correlation IDs (trace_id, session_id, event_id, parent_id, call_id) are strictly preserved.

        Args:
            event: TraceEvent to convert.
            resource_attributes: Optional resource-level attributes.

        Returns:
            Validated OTelSpan.
        """
        start_nano = _to_unix_nano(event.timestamp)
        end_nano = start_nano

        # Determine span name based on event kind and payload
        span_name = f"agentcontract.{event.event_kind.lower()}"
        if event.event_kind == EventKind.TOOL_CALL and isinstance(event.payload, ToolCall):
            span_name = f"tool.{event.payload.tool_name}"
        elif event.event_kind == EventKind.TOOL_RESULT and isinstance(event.payload, ToolResult):
            span_name = f"tool_result.{event.payload.call_id}"

        # Status mapping
        status_code = "OK"
        status_description: str | None = None

        attrs: dict[str, Any] = {
            "agentcontract.actor": str(event.actor),
            "agentcontract.event_id": event.event_id,
            "agentcontract.event_kind": str(event.event_kind),
            "agentcontract.sequence": event.sequence,
            "agentcontract.trace_id": event.trace_id,
        }

        if event.session_id:
            attrs["agentcontract.session_id"] = event.session_id
        if event.parent_id:
            attrs["agentcontract.parent_id"] = event.parent_id

        # Payload attributes and duration mapping
        payload = event.payload
        if isinstance(payload, ToolCall):
            attrs["agentcontract.tool.call_id"] = payload.call_id
            attrs["agentcontract.tool.name"] = payload.tool_name
            attrs["agentcontract.tool.arguments"] = json.dumps(
                dict(payload.arguments), default=str, sort_keys=True
            )

        elif isinstance(payload, ToolResult):
            attrs["agentcontract.tool.call_id"] = payload.call_id
            attrs["agentcontract.tool.status"] = str(payload.status)
            if payload.exit_code is not None:
                attrs["agentcontract.tool.exit_code"] = payload.exit_code
            if payload.duration_ms is not None:
                attrs["agentcontract.tool.duration_ms"] = payload.duration_ms
                end_nano = start_nano + int(payload.duration_ms * 1_000_000)
            if payload.error:
                attrs["agentcontract.tool.error"] = payload.error
                status_code = "ERROR"
                status_description = payload.error
            elif payload.status in (ToolResultStatus.ERROR, ToolResultStatus.TIMEOUT, ToolResultStatus.CANCELLED):
                status_code = "ERROR"
                status_description = f"Tool result ended in {payload.status}"

        elif isinstance(payload, GuardDecision):
            attrs["agentcontract.guard.decision"] = str(payload.decision)
            if payload.matched_constraint_ids:
                attrs["agentcontract.guard.matched_constraint_ids"] = list(payload.matched_constraint_ids)
            if payload.violating_constraint_ids:
                attrs["agentcontract.guard.violating_constraint_ids"] = list(payload.violating_constraint_ids)
            if payload.reasons:
                attrs["agentcontract.guard.reason"] = payload.reason
            if payload.decision == DecisionKind.BLOCK:
                status_code = "ERROR"
                status_description = payload.reason

        elif isinstance(payload, Mapping) and (
            event.event_kind == EventKind.GUARD_DECISION or "decision" in payload
        ):
            dec = str(payload.get("decision", ""))
            attrs["agentcontract.guard.decision"] = dec
            matched = payload.get("matched_constraint_ids")
            if matched:
                attrs["agentcontract.guard.matched_constraint_ids"] = list(matched)
            violating = payload.get("violating_constraint_ids")
            if violating:
                attrs["agentcontract.guard.violating_constraint_ids"] = list(violating)
            reasons = payload.get("reasons")
            reason_str = "; ".join(reasons) if reasons else payload.get("reason", "")
            if reason_str:
                attrs["agentcontract.guard.reason"] = reason_str
            if dec in (DecisionKind.BLOCK.value, "BLOCK"):
                status_code = "ERROR"
                status_description = reason_str or "Action blocked by guard"

        elif event.event_kind == EventKind.ERROR:
            status_code = "ERROR"
            status_description = str(payload) if payload else "Trace error event"

        # Merge event metadata deterministically
        for k, v in event.metadata.items():
            attr_key = f"agentcontract.metadata.{k}"
            attrs[attr_key] = v

        res_attrs = dict(cls.DEFAULT_RESOURCE_ATTRIBUTES)
        if resource_attributes:
            res_attrs.update(resource_attributes)

        return OTelSpan(
            name=span_name,
            trace_id=event.trace_id,
            span_id=event.event_id,
            parent_span_id=event.parent_id,
            session_id=event.session_id,
            start_time_unix_nano=start_nano,
            end_time_unix_nano=end_nano,
            status_code=status_code,
            status_description=status_description,
            attributes=FrozenDict(attrs),
            resource_attributes=FrozenDict(res_attrs),
        )

    @classmethod
    def export_trace(
        cls,
        trace_store: TraceStore,
        trace_id: str,
        *,
        resource_attributes: Mapping[str, Any] | None = None,
    ) -> OTelTraceExport:
        """Export all events in a trace from TraceStore into an OTelTraceExport container.

        Args:
            trace_store: TraceStore containing trace events.
            trace_id: Target trace identifier.
            resource_attributes: Optional resource-level attributes.

        Returns:
            OTelTraceExport holding all mapped spans.
        """
        events = trace_store.list_events(trace_id)
        session_id: str | None = None
        spans: list[OTelSpan] = []

        res_attrs = dict(cls.DEFAULT_RESOURCE_ATTRIBUTES)
        if resource_attributes:
            res_attrs.update(resource_attributes)

        for evt in events:
            if evt.session_id and not session_id:
                session_id = evt.session_id
            span = cls.export_event(evt, resource_attributes=res_attrs)
            spans.append(span)

        return OTelTraceExport(
            trace_id=trace_id,
            session_id=session_id,
            spans=tuple(spans),
            resource_attributes=FrozenDict(res_attrs),
        )

    @classmethod
    def export_events(
        cls,
        events: Sequence[TraceEvent],
        *,
        resource_attributes: Mapping[str, Any] | None = None,
    ) -> tuple[OTelSpan, ...]:
        """Export an arbitrary sequence of TraceEvents to OTelSpan models."""
        return tuple(cls.export_event(e, resource_attributes=resource_attributes) for e in events)
