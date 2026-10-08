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


from agentcontract.integrations.codex.state import (
    CodexSessionStore,
    CorruptedLedgerError,
    CorruptedSessionStateError,
)
import pytest


def _concurrent_process_worker(base_dir_str: str, session_id: str, worker_id: int) -> None:
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


def test_session_store_concurrency_no_data_loss(tmp_path: Path) -> None:
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    base_dir = tmp_path / "sessions"
    store = CodexSessionStore(base_dir=base_dir)
    session_id = "concurrent_spawned_session_test"

    # Pre-initialize session
    store.get_or_create_session(session_id)

    num_workers = 8
    processes = []
    for i in range(num_workers):
        p = ctx.Process(
            target=_concurrent_process_worker,
            args=(str(base_dir), session_id, i),
        )
        processes.append(p)

    for p in processes:
        p.start()

    for p in processes:
        p.join(timeout=15.0)
        assert p.exitcode == 0

    # Reload fresh session from disk
    verify_store = CodexSessionStore(base_dir=base_dir)
    _, ledger, trace_store, meta = verify_store.get_or_create_session(session_id)

    # Assert exactly num_workers constraints and trace events persisted without ANY data loss
    assert len(ledger) == num_workers
    for i in range(num_workers):
        assert f"c_{i}" in ledger

    assert len(trace_store) == num_workers
    for i in range(num_workers):
        assert trace_store.get_tool_call(meta["trace_id"], f"call_{i}").arguments == {"id": i}


def test_session_store_corrupted_ledger_raises_error_and_does_not_overwrite(tmp_path: Path) -> None:
    base_dir = tmp_path / "sessions"
    store = CodexSessionStore(base_dir=base_dir)
    session_id = "corrupted_ledger_test"

    # Create valid session with a constraint
    _, ledger, trace_store, meta = store.get_or_create_session(session_id)
    c = Constraint(
        id="c_important",
        name="protect_important",
        description="Important constraint",
        strength=ConstraintStrength.HARD,
        rule_effect=RuleEffect.DENY,
        provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
        scope=ConstraintScope(paths=("secrets/prod.key",)),
    )
    ledger.add(c)
    store.save_session(session_id, ledger, trace_store, meta)

    # Corrupt the ledger.json file on disk with malformed JSON
    ledger_path = store.get_session_dir(session_id) / "ledger.json"
    corrupt_content = "{ invalid json content: true, incomplete"
    ledger_path.write_text(corrupt_content, encoding="utf-8")

    # Attempting to load or run transaction must raise CorruptedLedgerError
    with pytest.raises(CorruptedLedgerError) as exc_info:
        store.get_or_create_session(session_id)
    assert "Corrupted or invalid constraint ledger file" in str(exc_info.value)

    # Verify that the corrupted file was NOT silently overwritten or deleted
    assert ledger_path.read_text(encoding="utf-8") == corrupt_content


def test_session_store_corrupted_trace_raises_error(tmp_path: Path) -> None:
    base_dir = tmp_path / "sessions"
    store = CodexSessionStore(base_dir=base_dir)
    session_id = "corrupted_trace_test"

    store.get_or_create_session(session_id)
    trace_path = store.get_session_dir(session_id) / "trace.json"
    trace_path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(CorruptedSessionStateError):
        store.get_or_create_session(session_id)
