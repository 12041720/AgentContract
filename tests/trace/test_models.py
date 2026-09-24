"""Tests for trace domain models, enums, immutability, and serialization."""

from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from agentcontract.common.immutable import FrozenDict
from agentcontract.trace.exceptions import TraceValidationError
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
    TracePointer,
)
from agentcontract.trace.store import TraceStore


def test_actor_kind_enum_values():
    """Verify ActorKind contains all required actor classifications."""
    assert ActorKind.USER == "USER"
    assert ActorKind.AGENT == "AGENT"
    assert ActorKind.TOOL == "TOOL"
    assert ActorKind.SYSTEM == "SYSTEM"
    assert ActorKind.GUARD == "GUARD"
    assert ActorKind.ENVIRONMENT == "ENVIRONMENT"


def test_event_kind_enum_values():
    """Verify EventKind contains all required event types."""
    assert EventKind.USER_MESSAGE == "USER_MESSAGE"
    assert EventKind.AGENT_MESSAGE == "AGENT_MESSAGE"
    assert EventKind.TOOL_CALL == "TOOL_CALL"
    assert EventKind.TOOL_RESULT == "TOOL_RESULT"
    assert EventKind.GUARD_DECISION == "GUARD_DECISION"
    assert EventKind.STATE_OBSERVATION == "STATE_OBSERVATION"
    assert EventKind.ERROR == "ERROR"


def test_tool_result_status_enum_values():
    """Verify ToolResultStatus distinguishes success, error, timeout, and cancelled."""
    assert ToolResultStatus.SUCCESS == "SUCCESS"
    assert ToolResultStatus.ERROR == "ERROR"
    assert ToolResultStatus.TIMEOUT == "TIMEOUT"
    assert ToolResultStatus.CANCELLED == "CANCELLED"


def test_empty_identifiers_rejected():
    """Empty or whitespace-only identifiers must be rejected across models."""
    with pytest.raises(ValidationError):
        TracePointer(trace_id="   ", event_id="evt-1")

    with pytest.raises(ValidationError):
        TracePointer(trace_id="tr-1", event_id="")

    with pytest.raises(ValidationError):
        ToolCall(call_id="", tool_name="bash")

    with pytest.raises(ValidationError):
        ToolCall(call_id="call-1", tool_name="   ")

    with pytest.raises(ValidationError):
        ToolResult(call_id=" ", status=ToolResultStatus.SUCCESS)

    with pytest.raises(ValidationError):
        TraceEvent(
            event_id="",
            trace_id="tr-1",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )

    with pytest.raises(ValidationError):
        TraceEvent(
            event_id="evt-1",
            trace_id="   ",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )


def test_model_immutability():
    """Models must be frozen and prohibit attribute mutation."""
    pointer = TracePointer(trace_id="tr-1", event_id="evt-1")
    with pytest.raises(ValidationError):
        pointer.trace_id = "tr-2"  # type: ignore

    call = ToolCall(call_id="c-1", tool_name="run", arguments={"cmd": "pwd"})
    with pytest.raises(ValidationError):
        call.tool_name = "other"  # type: ignore

    res = ToolResult(call_id="c-1", status=ToolResultStatus.SUCCESS, output="done")
    with pytest.raises(ValidationError):
        res.status = ToolResultStatus.ERROR  # type: ignore

    event = TraceEvent(
        event_id="evt-1",
        trace_id="tr-1",
        sequence=0,
        actor=ActorKind.USER,
        event_kind=EventKind.USER_MESSAGE,
        payload="Hello",
    )
    with pytest.raises(ValidationError):
        event.sequence = 1  # type: ignore


def test_backing_store_and_container_immutability():
    """Internal FrozenDict backing store must be structurally immutable."""
    call = ToolCall(
        call_id="c-1",
        tool_name="run",
        arguments={"flag": True, "nested": {"k": "v"}},
    )
    assert isinstance(call.arguments, FrozenDict)
    with pytest.raises(TypeError):
        call.arguments["flag"] = False
    with pytest.raises(TypeError):
        call.arguments._data["flag"] = False

    res = ToolResult(
        call_id="c-1",
        status=ToolResultStatus.SUCCESS,
        output={"key": "val"},
        metadata={"cost": 0.01},
    )
    assert isinstance(res.metadata, FrozenDict)
    with pytest.raises(TypeError):
        res.metadata["cost"] = 0.02
    with pytest.raises(TypeError):
        res.metadata._data["cost"] = 0.02

    event = TraceEvent(
        event_id="evt-1",
        trace_id="tr-1",
        sequence=0,
        actor=ActorKind.USER,
        event_kind=EventKind.USER_MESSAGE,
        metadata={"source": "cli"},
    )
    with pytest.raises(TypeError):
        event.metadata["source"] = "api"
    with pytest.raises(TypeError):
        event.metadata._data["source"] = "api"


def test_defensive_isolation_from_external_mutations():
    """External mutations on input dicts must not affect durable models."""
    raw_args = {"nested": {"count": 10}, "list": [1, 2]}
    call = ToolCall(call_id="c-1", tool_name="calc", arguments=raw_args)
    raw_args["nested"]["count"] = 999
    raw_args["list"].append(3)

    assert call.arguments["nested"]["count"] == 10
    assert call.arguments["list"] == (1, 2)

    raw_output = {"data": [100]}
    res = ToolResult(call_id="c-1", status=ToolResultStatus.SUCCESS, output=raw_output)
    raw_output["data"].append(200)

    assert res.output["data"] == (100,)


def test_timezone_naive_timestamp_rejected():
    """Timezone-naive datetime objects must be explicitly rejected."""
    naive_dt = datetime(2026, 9, 23, 12, 0, 0)
    with pytest.raises(ValidationError) as exc_info:
        TraceEvent(
            event_id="evt-1",
            trace_id="tr-1",
            sequence=0,
            timestamp=naive_dt,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    assert "timezone-aware" in str(exc_info.value)


def test_timezone_aware_timestamp_normalized_to_utc():
    """Timezone-aware timestamps with non-UTC offset must be converted to UTC."""
    tz_east = timezone(timedelta(hours=8))
    dt_east = datetime(2026, 9, 23, 16, 0, 0, tzinfo=tz_east)

    event = TraceEvent(
        event_id="evt-1",
        trace_id="tr-1",
        sequence=0,
        timestamp=dt_east,
        actor=ActorKind.USER,
        event_kind=EventKind.USER_MESSAGE,
    )
    assert event.timestamp.tzinfo == timezone.utc
    assert event.timestamp.hour == 8  # 16:00 UTC+8 == 08:00 UTC


def test_tool_result_status_distinctions():
    """ToolResult status distinctions: timeout, error, success, cancelled."""
    success_res = ToolResult(call_id="c-1", status=ToolResultStatus.SUCCESS, output="ok")
    assert success_res.is_success is True
    assert success_res.is_error is False
    assert success_res.is_timeout is False
    assert success_res.is_cancelled is False

    error_res = ToolResult(
        call_id="c-1",
        status=ToolResultStatus.ERROR,
        error="Permission denied",
        exit_code=1,
    )
    assert error_res.is_success is False
    assert error_res.is_error is True
    assert error_res.is_timeout is False
    assert error_res.is_cancelled is False
    assert error_res.error == "Permission denied"
    assert error_res.exit_code == 1

    timeout_res = ToolResult(
        call_id="c-1",
        status=ToolResultStatus.TIMEOUT,
        duration_ms=5000.0,
        error="Timed out after 5000ms",
    )
    assert timeout_res.is_success is False
    assert timeout_res.is_error is False
    assert timeout_res.is_timeout is True
    assert timeout_res.is_cancelled is False

    cancelled_res = ToolResult(call_id="c-1", status=ToolResultStatus.CANCELLED)
    assert cancelled_res.is_success is False
    assert cancelled_res.is_error is False
    assert cancelled_res.is_timeout is False
    assert cancelled_res.is_cancelled is True


def test_trace_event_payload_requirements():
    """TOOL_CALL requires ToolCall payload and TOOL_RESULT requires ToolResult payload."""
    # TOOL_CALL without ToolCall
    with pytest.raises(ValidationError) as exc_info:
        TraceEvent(
            event_id="evt-1",
            trace_id="tr-1",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload="invalid string payload",
        )
    assert "TOOL_CALL event requires ToolCall payload" in str(exc_info.value)

    # TOOL_RESULT without ToolResult
    with pytest.raises(ValidationError) as exc_info:
        TraceEvent(
            event_id="evt-2",
            trace_id="tr-1",
            sequence=1,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            payload=None,
        )
    assert "TOOL_RESULT event requires ToolResult payload" in str(exc_info.value)

    # Valid TOOL_CALL
    tc = ToolCall(call_id="c-1", tool_name="bash", arguments={"cmd": "ls"})
    event_tc = TraceEvent(
        event_id="evt-tc",
        trace_id="tr-1",
        sequence=0,
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        payload=tc,
    )
    assert event_tc.tool_call == tc
    assert event_tc.tool_result is None

    # Valid TOOL_RESULT
    tr = ToolResult(call_id="c-1", status=ToolResultStatus.SUCCESS, output="file.txt")
    event_tr = TraceEvent(
        event_id="evt-tr",
        trace_id="tr-1",
        sequence=1,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        payload=tr,
    )
    assert event_tr.tool_result == tr
    assert event_tr.tool_call is None


def test_trace_pointer_and_event_pointer_creation():
    """TracePointer creation and event.to_pointer() conversion."""
    event = TraceEvent(
        event_id="evt-msg-1",
        trace_id="tr-alpha",
        session_id="sess-100",
        sequence=0,
        actor=ActorKind.USER,
        event_kind=EventKind.USER_MESSAGE,
        payload="Build the project",
    )
    pointer = event.to_pointer()
    assert pointer.trace_id == "tr-alpha"
    assert pointer.event_id == "evt-msg-1"
    assert pointer.session_id == "sess-100"


def test_serialization_round_trip():
    """All models must serialize to JSON and reconstruct faithfully."""
    # ToolCall round-trip
    tc = ToolCall(call_id="tc-1", tool_name="read_file", arguments={"path": "main.py"})
    tc_json = tc.model_dump_json()
    tc_rebuilt = ToolCall.model_validate_json(tc_json)
    assert tc_rebuilt == tc
    assert tc_rebuilt.arguments["path"] == "main.py"

    # ToolResult round-trip
    tr = ToolResult(
        call_id="tc-1",
        status=ToolResultStatus.SUCCESS,
        output={"content": "print('hello')", "lines": 1},
        exit_code=0,
        duration_ms=12.5,
    )
    tr_json = tr.model_dump_json()
    tr_rebuilt = ToolResult.model_validate_json(tr_json)
    assert tr_rebuilt == tr
    assert tr_rebuilt.output["content"] == "print('hello')"

    # TraceEvent round-trip with ToolCall
    event = TraceEvent(
        event_id="evt-1",
        trace_id="tr-1",
        session_id="s-1",
        sequence=0,
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        payload=tc,
        metadata={"priority": "high"},
    )
    event_json = event.model_dump_json()
    event_rebuilt = TraceEvent.model_validate_json(event_json)
    assert event_rebuilt.event_id == event.event_id
    assert event_rebuilt.event_kind == EventKind.TOOL_CALL
    assert isinstance(event_rebuilt.payload, ToolCall)
    assert event_rebuilt.payload.call_id == tc.call_id
    assert event_rebuilt.tool_call == tc

    # TracePointer round-trip
    ptr = TracePointer(trace_id="tr-1", event_id="evt-1", session_id="s-1")
    ptr_json = ptr.model_dump_json()
    ptr_rebuilt = TracePointer.model_validate_json(ptr_json)
    assert ptr_rebuilt == ptr


def test_top_level_package_exports_trace():
    """Verify trace symbols exported from root agentcontract package."""
    from agentcontract import (
        ActorKind as RootActorKind,
        EventKind as RootEventKind,
        FrozenDict as RootFrozenDict,
        ToolCall as RootToolCall,
        ToolResult as RootToolResult,
        ToolResultStatus as RootToolResultStatus,
        TraceEvent as RootTraceEvent,
        TracePointer as RootTracePointer,
        TraceStore as RootTraceStore,
    )

    assert RootActorKind is ActorKind
    assert RootEventKind is EventKind
    assert RootToolCall is ToolCall
    assert RootToolResult is ToolResult
    assert RootToolResultStatus is ToolResultStatus
    assert RootTraceEvent is TraceEvent
    assert RootTracePointer is TracePointer
    assert RootTraceStore is TraceStore
    assert RootFrozenDict is FrozenDict


# --- BLOCKER 2 Regression Tests: ToolResult.output Immutability and Domain ---

def test_unsupported_mutable_and_custom_types_rejected_in_output():
    """BLOCKER: Unsupported mutable types, sets, non-finite floats, and custom objects must be rejected."""
    # bytearray rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-bytearray",
            status=ToolResultStatus.SUCCESS,
            output=bytearray(b"hello"),
        )
    assert "Unsupported trace value of type 'bytearray'" in str(exc_info.value)

    # bytes rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-bytes",
            status=ToolResultStatus.SUCCESS,
            output=b"raw bytes",
        )
    assert "Unsupported trace value of type 'bytes'" in str(exc_info.value)

    # set rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-set",
            status=ToolResultStatus.SUCCESS,
            output={"tag1", "tag2"},
        )
    assert "sets are not supported as durable trace values" in str(exc_info.value)

    # frozenset rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-frozenset",
            status=ToolResultStatus.SUCCESS,
            output=frozenset(["tag1", "tag2"]),
        )
    assert "sets are not supported as durable trace values" in str(exc_info.value)

    # NaN rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-nan",
            status=ToolResultStatus.SUCCESS,
            output=float("nan"),
        )
    assert "Non-finite float" in str(exc_info.value)

    # Infinity rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-inf",
            status=ToolResultStatus.SUCCESS,
            output=float("inf"),
        )
    assert "Non-finite float" in str(exc_info.value)

    # -Infinity rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-neginf",
            status=ToolResultStatus.SUCCESS,
            output=float("-inf"),
        )
    assert "Non-finite float" in str(exc_info.value)

    # arbitrary object instance rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-object",
            status=ToolResultStatus.SUCCESS,
            output=object(),
        )
    assert "Unsupported trace value of type 'object'" in str(exc_info.value)

    # custom class instance rejected
    class CustomObject:
        pass

    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-custom",
            status=ToolResultStatus.SUCCESS,
            output=CustomObject(),
        )
    assert "Unsupported trace value of type 'CustomObject'" in str(exc_info.value)

    # deeply nested unsupported mutable rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-nested-bad",
            status=ToolResultStatus.SUCCESS,
            output={"data": [1, {"flag": bytearray(b"nested")}]},
        )
    assert "Unsupported trace value of type 'bytearray'" in str(exc_info.value)

    # deeply nested set rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-nested-set",
            status=ToolResultStatus.SUCCESS,
            output={"data": (1, {"tags": {"a", "b"}})},
        )
    assert "sets are not supported as durable trace values" in str(exc_info.value)

    # deeply nested NaN rejected
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            call_id="c-nested-nan",
            status=ToolResultStatus.SUCCESS,
            output={"scores": [1.0, float("nan")]},
        )
    assert "Non-finite float" in str(exc_info.value)


def test_accepted_output_domain_json_round_trip():
    """BLOCKER: Accepted output domain values (scalars, FrozenDict, tuple) round-trip with exact semantic equality."""
    cases = [
        None,
        True,
        False,
        0,
        -42,
        3.14159,
        "standard string output",
        {"name": "agent", "count": 10, "nested": {"valid": True}},
        [1, "two", 3.0, None],
        (10, 20, 30),
        {"items": [1, {"nested_key": 2.5}], "flag": True},
    ]

    for expected_val in cases:
        tr = ToolResult(
            call_id="c-domain-test",
            status=ToolResultStatus.SUCCESS,
            output=expected_val,
        )
        json_repr = tr.model_dump_json()
        rebuilt = ToolResult.model_validate_json(json_repr)

        assert rebuilt.call_id == tr.call_id
        assert rebuilt.status == tr.status
        # Exact semantic equality: no weakened assertions or type loss
        assert rebuilt.output == tr.output
        if isinstance(expected_val, (list, tuple)):
            assert rebuilt.output == tuple(expected_val)
        elif isinstance(expected_val, dict):
            assert isinstance(rebuilt.output, FrozenDict)
        else:
            assert rebuilt.output == expected_val


def test_trace_event_durable_payload_domain_and_round_trip():
    """TraceEvent.payload supports the durable value domain and preserves exact semantic equality."""
    accepted_payloads = [
        None,
        True,
        False,
        0,
        12345,
        -99,
        3.14159,
        "plain text payload",
        {"agent": "coder", "step": 1, "nested": {"ok": True}},
        [1, "two", 3.0, None],
        (10, 20, 30),
        {"data": [1, {"k": 2.5}], "active": False},
    ]

    for payload_val in accepted_payloads:
        event = TraceEvent(
            event_id="evt-payload-test",
            trace_id="tr-test",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
            payload=payload_val,
        )
        json_repr = event.model_dump_json()
        rebuilt = TraceEvent.model_validate_json(json_repr)

        assert rebuilt.event_id == event.event_id
        assert rebuilt.event_kind == event.event_kind
        assert rebuilt.payload == event.payload
        if isinstance(payload_val, (list, tuple)):
            assert rebuilt.payload == tuple(payload_val)
        elif isinstance(payload_val, dict):
            assert isinstance(rebuilt.payload, FrozenDict)
        else:
            assert rebuilt.payload == payload_val


def test_trace_event_payload_unsupported_types_rejected():
    """TraceEvent.payload explicitly rejects unsupported types with TraceValidationError."""
    unsupported_payloads = [
        {"a", "b"},
        frozenset(["a", "b"]),
        float("nan"),
        float("inf"),
        float("-inf"),
        bytearray(b"payload"),
        b"raw bytes",
        object(),
        {"nested": {"bad_set": {1, 2}}},
        {"nested": [float("nan")]},
    ]

    for bad_payload in unsupported_payloads:
        with pytest.raises(ValidationError):
            TraceEvent(
                event_id="evt-bad-payload",
                trace_id="tr-test",
                sequence=0,
                actor=ActorKind.AGENT,
                event_kind=EventKind.AGENT_MESSAGE,
                payload=bad_payload,
            )


def test_tool_call_arguments_unsupported_types_rejected():
    """ToolCall.arguments rejects non-finite floats, sets, bytes, and invalid types."""
    unsupported_in_args = [
        {"tags": {"tag1", "tag2"}},
        {"tags": frozenset(["tag1", "tag2"])},
        {"score": float("nan")},
        {"score": float("inf")},
        {"data": bytearray(b"bytes")},
        {"data": b"bytes"},
        {"obj": object()},
    ]

    for bad_args in unsupported_in_args:
        with pytest.raises(ValidationError):
            ToolCall(
                call_id="c-bad-args",
                tool_name="test_tool",
                arguments=bad_args,
            )


def test_trace_pointer_blank_session_id_rejected():
    """Non-blocking cleanup: TracePointer.session_id must reject blank strings when provided."""
    with pytest.raises(ValidationError) as exc_info:
        TracePointer(trace_id="tr-1", event_id="evt-1", session_id="   ")
    assert "Identifier must not be empty or blank" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        TracePointer(trace_id="tr-1", event_id="evt-1", session_id="")
    assert "Identifier must not be empty or blank" in str(exc_info.value)

    # Valid session_id accepted
    p = TracePointer(trace_id="tr-1", event_id="evt-1", session_id="sess-valid")
    assert p.session_id == "sess-valid"

    # None session_id accepted
    p_none = TracePointer(trace_id="tr-1", event_id="evt-1", session_id=None)
    assert p_none.session_id is None
