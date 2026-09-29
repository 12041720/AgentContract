"""Tests for OpenTelemetry bridge and export models."""

from datetime import datetime, timezone
import json
import pytest

from agentcontract.adapters.otel import (
    OTelSpan,
    OTelTraceBridge,
    OTelTraceExport,
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
    assert spans[0]["traceId"] == t_id
    assert spans[0]["spanId"] == "e1"

    # Must be JSON-serializable
    dumped = json.dumps(otlp)
    assert t_id in dumped


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
