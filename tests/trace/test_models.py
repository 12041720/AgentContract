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
