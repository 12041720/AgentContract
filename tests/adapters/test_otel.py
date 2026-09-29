"""Tests for OpenTelemetry bridge and export models."""

from datetime import datetime, timezone
import json
import re
import pytest

from agentcontract.adapters.otel import (
    OTelSpan,
    OTelTraceBridge,
    OTelTraceExport,
    to_otlp_span_id,
    to_otlp_trace_id,
)
from agentcontract.guard.models import Action, ActionKind, DecisionKind, GuardDecision
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
)
from agentcontract.trace.store import TraceStore


def test_otel_span_preserves_correlation_ids() -> None:
    now = datetime.now(timezone.utc)
    evt = TraceEvent(
        event_id="evt_test_12345",
        trace_id="trace_session_abc",
        session_id="session_xyz_789",
        sequence=1,
        timestamp=now,
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        parent_id="evt_parent_000",
        payload=ToolCall(
            call_id="call_999",
            tool_name="test_tool",
            arguments={"param": "value"},
        ),
    )

    span = OTelTraceBridge.export_event(evt)
    assert isinstance(span, OTelSpan)
    # Correlation IDs must be strictly preserved
    assert span.trace_id == "trace_session_abc"
    assert span.span_id == "evt_test_12345"
    assert span.parent_span_id == "evt_parent_000"
    assert span.session_id == "session_xyz_789"
    assert span.attributes["agentcontract.tool.call_id"] == "call_999"
    assert span.attributes["agentcontract.tool.name"] == "test_tool"
    assert span.attributes["agentcontract.event_id"] == "evt_test_12345"
    assert span.attributes["agentcontract.trace_id"] == "trace_session_abc"
    assert span.attributes["agentcontract.sequence"] == 1


def test_otel_span_attributes_deterministic_and_sorted() -> None:
    now = datetime.now(timezone.utc)
    evt = TraceEvent(
        event_id="evt_sort_1",
        trace_id="trace_sort",
        sequence=0,
        timestamp=now,
        actor=ActorKind.SYSTEM,
        event_kind=EventKind.STATE_OBSERVATION,
        metadata={"zeta": 1, "alpha": "test", "beta": True},
    )

    span = OTelTraceBridge.export_event(evt)
    keys = list(span.attributes.keys())
    assert keys == sorted(keys), "Span attributes keys must be sorted deterministically."


def test_otel_span_status_mapping() -> None:
    now = datetime.now(timezone.utc)

    # SUCCESS tool result
    evt_succ = TraceEvent(
        event_id="evt_succ",
        trace_id="tr1",
        sequence=0,
        timestamp=now,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        payload=ToolResult(
            call_id="c1",
            status=ToolResultStatus.SUCCESS,
            output="ok",
        ),
    )
    span_succ = OTelTraceBridge.export_event(evt_succ)
    assert span_succ.status_code == "OK"

    # ERROR tool result
    evt_err = TraceEvent(
        event_id="evt_err",
        trace_id="tr1",
        sequence=1,
        timestamp=now,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        payload=ToolResult(
            call_id="c1",
            status=ToolResultStatus.ERROR,
            error="disk failure",
        ),
    )
    span_err = OTelTraceBridge.export_event(evt_err)
    assert span_err.status_code == "ERROR"
    assert span_err.status_description == "disk failure"

    # TIMEOUT tool result
    evt_to = TraceEvent(
        event_id="evt_to",
        trace_id="tr1",
        sequence=2,
        timestamp=now,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        payload=ToolResult(
            call_id="c1",
            status=ToolResultStatus.TIMEOUT,
        ),
    )
    span_to = OTelTraceBridge.export_event(evt_to)
    assert span_to.status_code == "ERROR"

    # GUARD BLOCK decision
    act = Action(tool_name="rm_rf", paths=("/etc",))
    dec_blk = GuardDecision(
        decision=DecisionKind.BLOCK,
        action=act,
        reasons=("Prohibited action",),
    )
    evt_blk = TraceEvent(
        event_id="evt_blk",
        trace_id="tr1",
        sequence=3,
        timestamp=now,
        actor=ActorKind.GUARD,
        event_kind=EventKind.GUARD_DECISION,
        payload=dec_blk.model_dump(mode="json"),
    )
    span_blk = OTelTraceBridge.export_event(evt_blk)
    assert span_blk.status_code == "ERROR"
    assert "Prohibited action" in span_blk.status_description

    # GUARD ALLOW decision
    dec_alw = GuardDecision(
        decision=DecisionKind.ALLOW,
        action=act,
    )
    evt_alw = TraceEvent(
        event_id="evt_alw",
        trace_id="tr1",
        sequence=4,
        timestamp=now,
        actor=ActorKind.GUARD,
        event_kind=EventKind.GUARD_DECISION,
        payload=dec_alw.model_dump(mode="json"),
    )
    span_alw = OTelTraceBridge.export_event(evt_alw)
    assert span_alw.status_code == "OK"


def test_otel_trace_bridge_export_trace_from_store() -> None:
    store = TraceStore()
    now = datetime.now(timezone.utc)
    t_id = "trace_multi_event"
    s_id = "sess_001"

    evt1 = TraceEvent(
        event_id="e1",
        trace_id=t_id,
        session_id=s_id,
        sequence=0,
        timestamp=now,
        actor=ActorKind.USER,
        event_kind=EventKind.USER_MESSAGE,
        payload="Run tests",
    )
    evt2 = TraceEvent(
        event_id="e2",
        trace_id=t_id,
        session_id=s_id,
        sequence=1,
        timestamp=now,
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        parent_id="e1",
        payload=ToolCall(call_id="c_pytest", tool_name="pytest", arguments={}),
    )
    evt3 = TraceEvent(
        event_id="e3",
        trace_id=t_id,
        session_id=s_id,
        sequence=2,
        timestamp=now,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        parent_id="e2",
        payload=ToolResult(call_id="c_pytest", status=ToolResultStatus.SUCCESS, output="all passed"),
    )

    store.append(evt1)
    store.append(evt2)
    store.append(evt3)

    export = OTelTraceBridge.export_trace(store, t_id)
    assert isinstance(export, OTelTraceExport)
    assert export.trace_id == t_id
    assert export.session_id == s_id
    assert len(export.spans) == 3
    assert export.spans[0].span_id == "e1"
    assert export.spans[1].parent_span_id == "e1"
    assert export.spans[2].parent_span_id == "e2"


def test_otel_trace_export_otlp_json_serialization() -> None:
    store = TraceStore()
    now = datetime.now(timezone.utc)
    t_id = "trace_otlp_test"

    store.append(
        TraceEvent(
            event_id="e1",
            trace_id=t_id,
            sequence=0,
            timestamp=now,
            actor=ActorKind.SYSTEM,
            event_kind=EventKind.STATE_OBSERVATION,
            payload="ready",
        )
    )

    export = OTelTraceBridge.export_trace(store, t_id)
    otlp = export.to_otlp_dict()
    assert "resourceSpans" in otlp
    assert len(otlp["resourceSpans"]) == 1
    spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 1
    assert spans[0]["traceId"] == to_otlp_trace_id(t_id)
    assert spans[0]["spanId"] == to_otlp_span_id("e1")

    # Must be JSON-serializable
    dumped = json.dumps(otlp)
    # Original trace ID is preserved in attributes
    assert t_id in dumped


def test_otlp_wire_id_formatting_and_non_zero() -> None:
    """OTLP traceId must be 32 hex, spanId must be 16 hex, neither may be all zeros."""
    trace_wire = to_otlp_trace_id("custom_domain_trace_123")
    assert re.fullmatch(r"^[0-9a-f]{32}$", trace_wire)
    assert trace_wire != "0" * 32

    span_wire = to_otlp_span_id("evt_custom_event_456")
    assert re.fullmatch(r"^[0-9a-f]{16}$", span_wire)
    assert span_wire != "0" * 16

    # Normalized lowercase if already valid hex
    valid_32 = "ABCDEF0123456789ABCDEF0123456789"
    assert to_otlp_trace_id(valid_32) == valid_32.lower()

    valid_16 = "A1B2C3D4E5F60718"
    assert to_otlp_span_id(valid_16) == valid_16.lower()


def test_otlp_wire_id_stability() -> None:
    """Same input must always produce the exact same wire ID across repeated calls."""
    trace_in = "stable_trace_id_xyz"
    first_trace = to_otlp_trace_id(trace_in)
    for _ in range(50):
        assert to_otlp_trace_id(trace_in) == first_trace

    span_in = "stable_event_id_abc"
    first_span = to_otlp_span_id(span_in)
    for _ in range(50):
        assert to_otlp_span_id(span_in) == first_span


def test_otlp_wire_id_distinctness_across_test_fixtures() -> None:
    """Distinct inputs must map to distinct wire IDs."""
    event_ids = [f"evt_{i:04d}" for i in range(100)]
    wire_spans = {to_otlp_span_id(eid) for eid in event_ids}
    assert len(wire_spans) == len(event_ids), "All distinct event IDs must map to distinct span IDs."

    trace_ids = [f"trace_{i:04d}" for i in range(50)]
    wire_traces = {to_otlp_trace_id(tid) for tid in trace_ids}
    assert len(wire_traces) == len(trace_ids), "All distinct trace IDs must map to distinct trace IDs."


def test_otlp_export_wire_ids_and_attribute_preservation() -> None:
    """Wire export conforms to OTLP schema while preserving domain correlation IDs in attributes."""
    store = TraceStore()
    now = datetime.now(timezone.utc)
    raw_trace_id = "agentcontract_trace_domain_001"
    raw_session_id = "sess_domain_002"

    evt_root = TraceEvent(
        event_id="evt_root_001",
        trace_id=raw_trace_id,
        session_id=raw_session_id,
        sequence=0,
        timestamp=now,
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        payload=ToolCall(call_id="call_root_1", tool_name="bash", arguments={"cmd": "ls"}),
    )
    evt_child = TraceEvent(
        event_id="evt_child_002",
        trace_id=raw_trace_id,
        session_id=raw_session_id,
        parent_id="evt_root_001",
        sequence=1,
        timestamp=now,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        payload=ToolResult(call_id="call_root_1", status=ToolResultStatus.SUCCESS, output="file.txt"),
    )
    store.append(evt_root)
    store.append(evt_child)

    export = OTelTraceBridge.export_trace(store, raw_trace_id)
    otlp = export.to_otlp_dict()

    spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 2

    # Wire IDs format
    root_span = spans[0]
    child_span = spans[1]

    assert re.fullmatch(r"^[0-9a-f]{32}$", root_span["traceId"])
    assert re.fullmatch(r"^[0-9a-f]{32}$", child_span["traceId"])
    assert root_span["traceId"] == child_span["traceId"] == to_otlp_trace_id(raw_trace_id)

    assert re.fullmatch(r"^[0-9a-f]{16}$", root_span["spanId"])
    assert re.fullmatch(r"^[0-9a-f]{16}$", child_span["spanId"])
    assert root_span["spanId"] != child_span["spanId"]

    # Root parentSpanId is empty string, child parentSpanId matches root spanId
    assert root_span["parentSpanId"] == ""
    assert child_span["parentSpanId"] == root_span["spanId"]
    assert re.fullmatch(r"^[0-9a-f]{16}$", child_span["parentSpanId"])

    # Attributes preserve original AgentContract IDs
    def attrs_to_dict(raw_attrs):
        res = {}
        for entry in raw_attrs:
            k = entry["key"]
            v_obj = entry["value"]
            if "stringValue" in v_obj:
                res[k] = v_obj["stringValue"]
            elif "intValue" in v_obj:
                res[k] = int(v_obj["intValue"])
        return res

    root_attrs = attrs_to_dict(root_span["attributes"])
    assert root_attrs["agentcontract.trace_id"] == raw_trace_id
    assert root_attrs["agentcontract.session_id"] == raw_session_id
    assert root_attrs["agentcontract.event_id"] == "evt_root_001"
    assert root_attrs["agentcontract.tool.call_id"] == "call_root_1"

    child_attrs = attrs_to_dict(child_span["attributes"])
    assert child_attrs["agentcontract.trace_id"] == raw_trace_id
    assert child_attrs["agentcontract.parent_id"] == "evt_root_001"
    assert child_attrs["agentcontract.event_id"] == "evt_child_002"
    assert child_attrs["agentcontract.tool.call_id"] == "call_root_1"


def test_otel_spans_serializable_and_immutable() -> None:
    now = datetime.now(timezone.utc)
    evt = TraceEvent(
        event_id="evt_imm",
        trace_id="tr_imm",
        sequence=0,
        timestamp=now,
        actor=ActorKind.AGENT,
        event_kind=EventKind.AGENT_MESSAGE,
        payload="hello",
    )
    span = OTelTraceBridge.export_event(evt)

    # Immutability
    with pytest.raises(Exception):
        span.name = "new_name"  # type: ignore[misc]

    # JSON round trip
    data = span.to_dict()
    round_trip = OTelSpan.model_validate(data)
    assert round_trip == span
