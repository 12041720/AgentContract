"""Tests for TraceStore invariants, ordering, correlation, and serialization."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from agentcontract.trace.exceptions import (
    DuplicateEventError,
    EventNotFoundError,
    InvalidSequenceError,
    ParentEventError,
    ToolCorrelationError,
    TraceValidationError,
)
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


def test_scenario_1_user_agent_tool_call_tool_result_workflow():
    """Scenario 1: Standard agent execution flow.

    user instruction -> agent message -> tool call -> tool result.
    """
    store = TraceStore()

    # 1. User instruction
    e1 = store.append(
        TraceEvent(
            event_id="evt-1",
            trace_id="tr-1",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
            payload="Please check disk space",
        )
    )

    # 2. Agent message
    e2 = store.append(
        TraceEvent(
            event_id="evt-2",
            trace_id="tr-1",
            parent_id="evt-1",
            sequence=1,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
            payload="Checking disk usage with df command",
        )
    )

    # 3. Tool call
    tc = ToolCall(call_id="call-df-1", tool_name="df", arguments={"flag": "-h"})
    e3 = store.append(
        TraceEvent(
            event_id="evt-3",
            trace_id="tr-1",
            parent_id="evt-2",
            sequence=2,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc,
        )
    )

    # 4. Tool result
    tr = ToolResult(
        call_id="call-df-1",
        status=ToolResultStatus.SUCCESS,
        output="Filesystem 50G used 20G avail 30G",
        exit_code=0,
    )
    e4 = store.append(
        TraceEvent(
            event_id="evt-4",
            trace_id="tr-1",
            parent_id="evt-3",
            sequence=3,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            payload=tr,
        )
    )

    assert len(store) == 4
    events = store.list_events("tr-1")
    assert [e.event_id for e in events] == ["evt-1", "evt-2", "evt-3", "evt-4"]
    assert store.get_tool_call("tr-1", "call-df-1") == tc
    assert store.get_tool_result("tr-1", "call-df-1") == tr


def test_scenario_2_interleaved_traces_independent_monotonic_sequences():
    """Scenario 2: Two traces interleaved in one store retain independent monotonic sequences."""
    store = TraceStore()

    store.append(
        TraceEvent(
            event_id="t1-e0",
            trace_id="trace-1",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )
    store.append(
        TraceEvent(
            event_id="t2-e0",
            trace_id="trace-2",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )
    store.append(
        TraceEvent(
            event_id="t1-e1",
            trace_id="trace-1",
            sequence=1,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
        )
    )
    store.append(
        TraceEvent(
            event_id="t2-e1",
            trace_id="trace-2",
            sequence=5,  # Gaps are allowed, but must be strictly increasing
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
        )
    )
    store.append(
        TraceEvent(
            event_id="t1-e2",
            trace_id="trace-1",
            sequence=2,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
        )
    )

    t1_events = store.list_events("trace-1")
    t2_events = store.list_events("trace-2")

    assert [e.event_id for e in t1_events] == ["t1-e0", "t1-e1", "t1-e2"]
    assert [e.sequence for e in t1_events] == [0, 1, 2]

    assert [e.event_id for e in t2_events] == ["t2-e0", "t2-e1"]
    assert [e.sequence for e in t2_events] == [0, 5]


def test_scenario_3_duplicate_event_id_rejection():
    """Scenario 3: Duplicate event ID rejection across the store."""
    store = TraceStore()
    store.append(
        TraceEvent(
            event_id="evt-dup",
            trace_id="tr-1",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )

    with pytest.raises(DuplicateEventError) as exc_info:
        store.append(
            TraceEvent(
                event_id="evt-dup",
                trace_id="tr-2",
                sequence=0,
                actor=ActorKind.USER,
                event_kind=EventKind.USER_MESSAGE,
            )
        )
    assert "already exists in store" in str(exc_info.value)


def test_scenario_4_duplicate_or_decreasing_sequence_rejection_within_trace():
    """Scenario 4: Duplicate or decreasing sequence numbers within the same trace must fail explicitly."""
    store = TraceStore()
    store.append(
        TraceEvent(
            event_id="e-seq-1",
            trace_id="tr-seq",
            sequence=5,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )

    # Duplicate sequence (5)
    with pytest.raises(InvalidSequenceError) as exc_info:
        store.append(
            TraceEvent(
                event_id="e-seq-dup",
                trace_id="tr-seq",
                sequence=5,
                actor=ActorKind.AGENT,
                event_kind=EventKind.AGENT_MESSAGE,
            )
        )
    assert "not strictly greater than previous sequence 5" in str(exc_info.value)

    # Decreasing sequence (4)
    with pytest.raises(InvalidSequenceError) as exc_info:
        store.append(
            TraceEvent(
                event_id="e-seq-dec",
                trace_id="tr-seq",
                sequence=4,
                actor=ActorKind.AGENT,
                event_kind=EventKind.AGENT_MESSAGE,
            )
        )
    assert "not strictly greater than previous sequence 5" in str(exc_info.value)


def test_scenario_5_same_sequence_allowed_in_different_trace_ids():
    """Scenario 5: The same sequence numbers are valid across distinct trace IDs."""
    store = TraceStore()
    e_a = store.append(
        TraceEvent(
            event_id="trA-0",
            trace_id="trace-A",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )
    e_b = store.append(
        TraceEvent(
            event_id="trB-0",
            trace_id="trace-B",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )
    assert e_a.sequence == 0
    assert e_b.sequence == 0
    assert len(store) == 2


def test_scenario_6_duplicate_tool_call_id_rejection_within_trace():
    """Scenario 6: Reusing the same ToolCallId for multiple tool calls in one trace is rejected."""
    store = TraceStore()
    store.append(
        TraceEvent(
            event_id="e-tc-1",
            trace_id="tr-call",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=ToolCall(call_id="call-unique-1", tool_name="bash"),
        )
    )

    # Attempt second tool call in same trace with identical call_id
    with pytest.raises(ToolCorrelationError) as exc_info:
        store.append(
            TraceEvent(
                event_id="e-tc-2",
                trace_id="tr-call",
                sequence=1,
                actor=ActorKind.AGENT,
                event_kind=EventKind.TOOL_CALL,
                payload=ToolCall(call_id="call-unique-1", tool_name="python"),
            )
        )
    assert "Duplicate ToolCallId 'call-unique-1'" in str(exc_info.value)


def test_scenario_7_tool_result_unknown_call_id_rejection():
    """Scenario 7: A ToolResult with an unknown call ID in the trace must be rejected."""
    store = TraceStore()
    store.append(
        TraceEvent(
            event_id="e-user",
            trace_id="tr-tool",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )

    with pytest.raises(ToolCorrelationError) as exc_info:
        store.append(
            TraceEvent(
                event_id="e-tr-unknown",
                trace_id="tr-tool",
                sequence=1,
                actor=ActorKind.TOOL,
                event_kind=EventKind.TOOL_RESULT,
                payload=ToolResult(call_id="non-existent-call", status=ToolResultStatus.SUCCESS),
            )
        )
    assert "does not match any prior ToolCall" in str(exc_info.value)


def test_scenario_8_tool_result_belonging_to_another_trace_rejection():
    """Scenario 8: A ToolResult referencing a call_id from another trace must be rejected."""
    store = TraceStore()

    # Tool call issued in trace-alpha
    store.append(
        TraceEvent(
            event_id="e-alpha-tc",
            trace_id="trace-alpha",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=ToolCall(call_id="call-alpha-1", tool_name="ls"),
        )
    )

    # Tool result trying to resolve call-alpha-1 inside trace-beta
    with pytest.raises(ToolCorrelationError) as exc_info:
        store.append(
            TraceEvent(
                event_id="e-beta-tr",
                trace_id="trace-beta",
                sequence=0,
                actor=ActorKind.TOOL,
                event_kind=EventKind.TOOL_RESULT,
                payload=ToolResult(call_id="call-alpha-1", status=ToolResultStatus.SUCCESS),
            )
        )
    assert "belongs to trace 'trace-alpha', not the current trace 'trace-beta'" in str(exc_info.value)


def test_scenario_9_mismatched_parent_trace_or_event_rejection():
    """Scenario 9: Parent-event references must refer to an already-known event in the same trace."""
    store = TraceStore()

    store.append(
        TraceEvent(
            event_id="parent-alpha",
            trace_id="trace-alpha",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )

    # Non-existent parent event
    with pytest.raises(ParentEventError) as exc_info:
        store.append(
            TraceEvent(
                event_id="child-ghost",
                trace_id="trace-alpha",
                parent_id="ghost-parent",
                sequence=1,
                actor=ActorKind.AGENT,
                event_kind=EventKind.AGENT_MESSAGE,
            )
        )
    assert "Parent event 'ghost-parent' does not exist" in str(exc_info.value)

    # Parent event belongs to a different trace
    with pytest.raises(ParentEventError) as exc_info:
        store.append(
            TraceEvent(
                event_id="child-beta",
                trace_id="trace-beta",
                parent_id="parent-alpha",
                sequence=0,
                actor=ActorKind.AGENT,
                event_kind=EventKind.AGENT_MESSAGE,
            )
        )
    assert "belongs to trace 'trace-alpha', but event 'child-beta' belongs to trace 'trace-beta'" in str(
        exc_info.value
    )


def test_scenario_10_timezone_naive_timestamp_handling():
    """Scenario 10: Naive timestamps are rejected explicitly with TraceValidationError."""
    naive_dt = datetime(2026, 9, 23, 10, 0, 0)
    with pytest.raises(ValidationError):
        TraceEvent(
            event_id="e-naive",
            trace_id="tr-naive",
            sequence=0,
            timestamp=naive_dt,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )


def test_scenario_11_timeout_result_distinct_from_success_and_error():
    """Scenario 11: Timeout result remains distinct from success and error."""
    store = TraceStore()
    store.append(
        TraceEvent(
            event_id="tc-evt",
            trace_id="tr-timeout",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=ToolCall(call_id="call-timeout", tool_name="fetch_url"),
        )
    )

    tr_timeout = ToolResult(
        call_id="call-timeout",
        status=ToolResultStatus.TIMEOUT,
        duration_ms=30000.0,
        error="Gateway timed out after 30s",
        output=None,
    )
    store.append(
        TraceEvent(
            event_id="tr-evt",
            trace_id="tr-timeout",
            sequence=1,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            payload=tr_timeout,
        )
    )

    retrieved_tr = store.get_tool_result("tr-timeout", "call-timeout")
    assert retrieved_tr.is_timeout is True
    assert retrieved_tr.is_success is False
    assert retrieved_tr.is_error is False
    assert retrieved_tr.status == ToolResultStatus.TIMEOUT
    assert retrieved_tr.duration_ms == 30000.0


def test_scenario_12_external_dict_mutation_cannot_alter_stored_history():
    """Scenario 12: External argument/output dict mutation cannot alter stored history."""
    store = TraceStore()
    args = {"query": "SELECT 1", "options": {"timeout": 30}}
    call = ToolCall(call_id="call-db-1", tool_name="db_query", arguments=args)
    store.append(
        TraceEvent(
            event_id="evt-tc-db",
            trace_id="tr-db",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=call,
        )
    )

    # Mutate original external dict
    args["query"] = "DROP TABLE users;"
    args["options"]["timeout"] = 0

    stored_call = store.get_tool_call("tr-db", "call-db-1")
    assert stored_call.arguments["query"] == "SELECT 1"
    assert stored_call.arguments["options"]["timeout"] == 30


def test_scenario_13_trace_pointer_survives_serialization_and_resolves():
    """Scenario 13: TracePointer survives serialization round-trip and resolves to the same event."""
    store = TraceStore()
    e = store.append(
        TraceEvent(
            event_id="target-evt-99",
            trace_id="trace-ptr",
            session_id="session-user-1",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
            payload="Important directive",
        )
    )

    pointer = store.create_pointer("target-evt-99")
    assert pointer.trace_id == "trace-ptr"
    assert pointer.event_id == "target-evt-99"
    assert pointer.session_id == "session-user-1"

    # Serialize pointer and reconstruct
    ptr_json = pointer.model_dump_json()
    reconstructed_ptr = TracePointer.model_validate_json(ptr_json)

    resolved_event = store.resolve_pointer(reconstructed_ptr)
    assert resolved_event == e
    assert resolved_event.payload == "Important directive"


def test_scenario_14_deterministic_filtering():
    """Scenario 14: Filtering by actor, event kind, session, and trace is deterministic."""
    store = TraceStore()

    # Trace 1
    store.append(
        TraceEvent(
            event_id="e1",
            trace_id="t1",
            session_id="s1",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )
    store.append(
        TraceEvent(
            event_id="e2",
            trace_id="t1",
            session_id="s1",
            sequence=1,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
        )
    )
    store.append(
        TraceEvent(
            event_id="e3",
            trace_id="t1",
            session_id="s1",
            sequence=2,
            actor=ActorKind.GUARD,
            event_kind=EventKind.GUARD_DECISION,
        )
    )

    # Trace 2
    store.append(
        TraceEvent(
            event_id="e4",
            trace_id="t2",
            session_id="s2",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
        )
    )
    store.append(
        TraceEvent(
            event_id="e5",
            trace_id="t2",
            session_id="s2",
            sequence=1,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
        )
    )

    # Filter by trace
    t1_only = store.filter(trace_id="t1")
    assert [e.event_id for e in t1_only] == ["e1", "e2", "e3"]

    # Filter by actor
    agents = store.filter(actor=ActorKind.AGENT)
    assert [e.event_id for e in agents] == ["e2", "e5"]

    # Filter by event kind
    guards = store.filter(event_kind=EventKind.GUARD_DECISION)
    assert [e.event_id for e in guards] == ["e3"]

    # Filter by session
    s2_only = store.filter(session_id="s2")
    assert [e.event_id for e in s2_only] == ["e4", "e5"]

    # Combined filter
    t1_user = store.filter(trace_id="t1", actor=ActorKind.USER)
    assert [e.event_id for e in t1_user] == ["e1"]


def test_scenario_15_complete_store_json_round_trip_preserves_equality_and_order():
    """Scenario 15: Complete store JSON round-trip preserves semantic equality and order."""
    store = TraceStore()

    store.append(
        TraceEvent(
            event_id="e1",
            trace_id="t1",
            session_id="s1",
            sequence=0,
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
            payload="Start task",
        )
    )
    tc = ToolCall(call_id="c1", tool_name="bash", arguments={"cmd": "echo 1"})
    store.append(
        TraceEvent(
            event_id="e2",
            trace_id="t1",
            session_id="s1",
            parent_id="e1",
            sequence=1,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc,
        )
    )
    tr = ToolResult(
        call_id="c1",
        status=ToolResultStatus.SUCCESS,
        output="1\n",
        exit_code=0,
        duration_ms=45.2,
    )
    store.append(
        TraceEvent(
            event_id="e3",
            trace_id="t1",
            session_id="s1",
            parent_id="e2",
            sequence=2,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            payload=tr,
        )
    )

    json_str = store.to_json(indent=2)
    reconstructed_store = TraceStore.from_json(json_str)

    assert reconstructed_store == store
    assert len(reconstructed_store) == 3
    assert [e.event_id for e in reconstructed_store.list_events()] == ["e1", "e2", "e3"]
    assert reconstructed_store.get_tool_call("t1", "c1") == tc
    assert reconstructed_store.get_tool_result("t1", "c1") == tr


def test_invariant_12_agent_message_does_not_infer_success():
    """Invariant 12: The trace layer must not infer success merely from an agent message."""
    store = TraceStore()
    e = store.append(
        TraceEvent(
            event_id="msg-claim",
            trace_id="tr-test",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
            payload="Task completed successfully and all tests pass!",
        )
    )
    # The event is purely an AGENT_MESSAGE event; store does not alter or synthesize tool status
    assert e.event_kind == EventKind.AGENT_MESSAGE
    assert e.tool_call is None
    assert e.tool_result is None
    # No tool results exist
    with pytest.raises(ToolCorrelationError):
        store.get_tool_result("tr-test", "any-call")


def test_store_container_operations_and_error_handling():
    """Test get, get_optional, in operator, and corrupted store initialization."""
    store = TraceStore()
    e = TraceEvent(
        event_id="evt-1",
        trace_id="tr-1",
        sequence=0,
        actor=ActorKind.USER,
        event_kind=EventKind.USER_MESSAGE,
    )
    store.append(e)

    assert "evt-1" in store
    assert "evt-missing" not in store
    assert store.get("evt-1") == e
    assert store.get_optional("evt-missing") is None

    with pytest.raises(EventNotFoundError):
        store.get("evt-missing")

    # Initializing from existing iterable
    store2 = TraceStore([e])
    assert len(store2) == 1

    # Corrupted iterable with duplicate event_id
    with pytest.raises(DuplicateEventError):
        TraceStore([e, e])
