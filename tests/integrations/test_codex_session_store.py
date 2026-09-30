"""Tests for CodexSessionStore persistence, isolation, and integrity."""

from pathlib import Path
from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.integrations.codex.state import CodexSessionStore
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
)
from agentcontract.trace.store import TraceStore
from datetime import datetime, timezone


def test_session_store_create_and_round_trip(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")

    session_id = "test-session-001"
    trace_id, ledger, trace_store, meta = store.get_or_create_session(session_id)
    assert trace_id == "trace_test-session-001"

    # Add a constraint
    c = Constraint(
        id="c_test_1",
        name="protect_keys",
        description="Do not modify secrets/prod.key",
        strength=ConstraintStrength.HARD,
        rule_effect=RuleEffect.DENY,
        provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
        scope=ConstraintScope(paths=("secrets/prod.key",), actions=("FILE_WRITE",)),
    )
    ledger.add(c)

    # Add a tool call event
    tc = ToolCall(call_id="call_01", tool_name="read_file", arguments={"path": "src/app.py"})
    ev1 = TraceEvent(
        event_id="evt_01",
        trace_id=trace_id,
        session_id=session_id,
        sequence=0,
        timestamp=datetime.now(timezone.utc),
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        payload=tc,
    )
    trace_store.append(ev1)

    # Save
    store.save_session(session_id, ledger, trace_store, meta)
    assert store.session_exists(session_id)

    # Reload in a new store instance
    new_store = CodexSessionStore(base_dir=tmp_path / "sessions")
    r_trace_id, r_ledger, r_trace_store, r_meta = new_store.get_or_create_session(session_id)

    assert r_trace_id == trace_id
    assert len(r_ledger) == 1
    assert r_ledger.get("c_test_1").name == "protect_keys"
    assert len(r_trace_store) == 1
    assert r_trace_store.get_tool_call(trace_id, "call_01").tool_name == "read_file"


def test_session_store_isolation(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")

    # Session A
    _, ledger_a, trace_a, meta_a = store.get_or_create_session("session_A")
    c_a = Constraint(
        id="c_a",
        name="rule_a",
        description="Rule A",
        strength=ConstraintStrength.HARD,
        rule_effect=RuleEffect.DENY,
        provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
        scope=ConstraintScope(paths=("a.txt",)),
    )
    ledger_a.add(c_a)
    store.save_session("session_A", ledger_a, trace_a, meta_a)

    # Session B
    _, ledger_b, trace_b, meta_b = store.get_or_create_session("session_B")
    assert len(ledger_b) == 0  # Completely isolated from session A

    sessions = store.list_sessions()
    session_ids = {s["session_id"] for s in sessions}
    assert "session_A" in session_ids
    assert "session_B" in session_ids


def test_session_store_delete(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    store.get_or_create_session("to_delete")
    assert store.session_exists("to_delete")

    deleted = store.delete_session("to_delete")
    assert deleted is True
    assert not store.session_exists("to_delete")
