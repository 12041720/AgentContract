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


def _concurrent_worker(args: tuple[str, str, int]) -> int:
    base_dir_str, session_id, worker_id = args
    store = CodexSessionStore(base_dir=base_dir_str)
    with store.session_transaction(session_id) as tx:
        c = Constraint(
            id=f"c_{worker_id}",
            name=f"rule_{worker_id}",
            description=f"Rule from worker {worker_id}",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            provenance=ConstraintProvenance(source=ConstraintSource.USER, author=f"Worker_{worker_id}"),
            scope=ConstraintScope(paths=(f"path_{worker_id}.txt",)),
        )
        tx.ledger.add(c)
        tc = ToolCall(call_id=f"call_{worker_id}", tool_name="check", arguments={"id": worker_id})
        ev = TraceEvent(
            event_id=f"evt_{worker_id}",
            trace_id=tx.trace_id,
            session_id=session_id,
            sequence=len(tx.trace_store.list_events(tx.trace_id)),
            timestamp=datetime.now(timezone.utc),
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc,
        )
        tx.trace_store.append(ev)
    return worker_id


def test_session_store_concurrency_no_data_loss(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    base_dir = tmp_path / "sessions"
    store = CodexSessionStore(base_dir=base_dir)
    session_id = "concurrent_session_test"

    # Pre-initialize session
    store.get_or_create_session(session_id)

    num_workers = 10
    worker_args = [(str(base_dir), session_id, i) for i in range(num_workers)]

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_concurrent_worker, worker_args))

    assert len(results) == num_workers

    # Reload fresh session from disk
    verify_store = CodexSessionStore(base_dir=base_dir)
    _, ledger, trace_store, meta = verify_store.get_or_create_session(session_id)

    # Assert exactly 10 constraints and 10 trace events persisted without ANY data loss
    assert len(ledger) == num_workers
    for i in range(num_workers):
        assert f"c_{i}" in ledger

    assert len(trace_store) == num_workers
    for i in range(num_workers):
        assert trace_store.get_tool_call(meta["trace_id"], f"call_{i}").arguments == {"id": i}
