"""Tests for EvidenceGate deterministic verification, precedence, and evidence graph."""

import pytest

from agentcontract.evidence.gate import EvidenceGate
from agentcontract.evidence.graph import EvidenceGraph
from agentcontract.evidence.models import (
    Claim,
    ClaimEvaluation,
    ClaimType,
    ClaimVerdict,
    EvidenceRef,
    EvidenceRelation,
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


def _make_store_with_call_and_result(
    trace_id: str = "tr-1",
    call_id: str = "call-1",
    tool_name: str = "pytest",
    cmd: str = "pytest -v",
    status: ToolResultStatus = ToolResultStatus.SUCCESS,
    exit_code: int = 0,
    output: str | dict | None = "100 passed",
    error: str | None = None,
) -> TraceStore:
    """Helper to populate a TraceStore with a correlated ToolCall and ToolResult."""
    store = TraceStore()
    tc = ToolCall(call_id=call_id, tool_name=tool_name, arguments={"cmd": cmd})
    evt_call = TraceEvent(
        event_id=f"evt-{call_id}-call",
        trace_id=trace_id,
        sequence=0,
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        payload=tc,
    )
    store.append(evt_call)

    tr = ToolResult(
        call_id=call_id,
        status=status,
        exit_code=exit_code,
        output=output,
        error=error,
    )
    evt_res = TraceEvent(
        event_id=f"evt-{call_id}-res",
        trace_id=trace_id,
        sequence=1,
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        parent_id=evt_call.event_id,
        payload=tr,
    )
    store.append(evt_res)
    return store


# --- Scenario 1: Successful ToolResult verifies TOOL_SUCCEEDED ---

def test_scenario_1_successful_tool_result_verifies_tool_succeeded():
    """Scenario 1: A matching ToolResult with status SUCCESS verifies TOOL_SUCCEEDED."""
    store = _make_store_with_call_and_result(
        trace_id="tr-1",
        call_id="c-deploy",
        tool_name="deployer",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-deploy",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Deployment tool succeeded",
        trace_id="tr-1",
        call_id="c-deploy",
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.VERIFIED
    assert evaluation.is_verified is True
    assert len(evaluation.supporting_evidence) == 1
    assert evaluation.supporting_evidence[0].call_id == "c-deploy"
    assert evaluation.supporting_evidence[0].relation == EvidenceRelation.SUPPORTS
    assert len(evaluation.contradicting_evidence) == 0


# --- Scenario 2: ERROR result contradicts TOOL_SUCCEEDED ---

def test_scenario_2_error_result_contradicts_tool_succeeded():
    """Scenario 2: A ToolResult with status ERROR contradicts TOOL_SUCCEEDED."""
    store = _make_store_with_call_and_result(
        trace_id="tr-1",
        call_id="c-git-push",
        tool_name="git",
        status=ToolResultStatus.ERROR,
        exit_code=1,
        error="Remote rejected push",
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-git-push",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Git push completed successfully",
        trace_id="tr-1",
        call_id="c-git-push",
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.CONTRADICTED
    assert evaluation.is_contradicted is True
    assert len(evaluation.contradicting_evidence) == 1
    assert evaluation.contradicting_evidence[0].relation == EvidenceRelation.CONTRADICTS
    assert "Remote rejected push" in evaluation.reason or "ERROR" in evaluation.reason


# --- Scenario 3: TIMEOUT contradicts success ---

def test_scenario_3_timeout_contradicts_success():
    """Scenario 3: A ToolResult with status TIMEOUT contradicts success."""
    store = _make_store_with_call_and_result(
        trace_id="tr-1",
        call_id="c-build",
        tool_name="mvn",
        status=ToolResultStatus.TIMEOUT,
        error="Execution timed out after 300000ms",
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-mvn-build",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Maven build succeeded",
        trace_id="tr-1",
        call_id="c-build",
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.CONTRADICTED
    assert evaluation.is_contradicted is True
    assert len(evaluation.contradicting_evidence) == 1
    assert "TIMEOUT" in evaluation.reason


# --- Scenario 4: No result -> UNVERIFIED ---

def test_scenario_4_no_result_is_unverified():
    """Scenario 4: Missing evidence in the trace store results in UNVERIFIED."""
    store = TraceStore()
    # Tool call was issued but no result was ever recorded
    tc = ToolCall(call_id="c-pending", tool_name="long_task", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-pending-call",
            trace_id="tr-pending",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc,
        )
    )

    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-pending",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Long task completed",
        trace_id="tr-pending",
        call_id="c-pending",
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.UNVERIFIED
    assert evaluation.is_unverified is True
    assert len(evaluation.supporting_evidence) == 0
    assert len(evaluation.contradicting_evidence) == 0
    assert "No matching ToolResult" in evaluation.reason


# --- Scenario 5: AGENT_MESSAGE alone -> UNVERIFIED ---

def test_scenario_5_agent_message_alone_does_not_verify():
    """Scenario 5: An AGENT_MESSAGE asserting 'tests passed' is NEVER evidence and yields UNVERIFIED."""
    store = TraceStore()
    # Agent asserts tests passed in message text
    store.append(
        TraceEvent(
            event_id="evt-agent-msg",
            trace_id="tr-msg-only",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.AGENT_MESSAGE,
            payload="All unit tests passed successfully! 100% green.",
        )
    )

    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-test-asserted",
        claim_type=ClaimType.TESTS_PASSED,
        description="Unit tests passed",
        trace_id="tr-msg-only",
        tool_name="pytest",
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.UNVERIFIED
    assert evaluation.is_unverified is True
    assert len(evaluation.supporting_evidence) == 0


# --- Scenario 6: Matching test ToolResult success + exit 0 -> VERIFIED ---

def test_scenario_6_matching_test_tool_result_success_and_exit_0_verifies():
    """Scenario 6: Test ToolResult with SUCCESS status and exit code 0 verifies TESTS_PASSED."""
    store = _make_store_with_call_and_result(
        trace_id="tr-pytest",
        call_id="c-pytest-1",
        tool_name="pytest",
        cmd="pytest -v",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
        output="15 passed in 0.42s",
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-pytest",
        claim_type=ClaimType.TESTS_PASSED,
        description="Pytest test suite passed",
        trace_id="tr-pytest",
        call_id="c-pytest-1",
        expected_exit_code=0,
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.VERIFIED
    assert evaluation.is_verified is True
    assert len(evaluation.supporting_evidence) == 1
    assert evaluation.supporting_evidence[0].call_id == "c-pytest-1"


# --- Scenario 7: Test ToolResult exit 1 -> CONTRADICTED ---

def test_scenario_7_test_tool_result_exit_1_contradicts():
    """Scenario 7: Test ToolResult with exit code 1 contradicts TESTS_PASSED."""
    store = _make_store_with_call_and_result(
        trace_id="tr-pytest-fail",
        call_id="c-pytest-fail",
        tool_name="pytest",
        cmd="pytest -v",
        status=ToolResultStatus.SUCCESS,  # Command executed, but test suite returned 1
        exit_code=1,
        output="FAILED tests/test_foo.py::test_bar - AssertionError",
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-pytest-should-pass",
        claim_type=ClaimType.TESTS_PASSED,
        description="Pytest test suite passed",
        trace_id="tr-pytest-fail",
        call_id="c-pytest-fail",
        expected_exit_code=0,
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.CONTRADICTED
    assert evaluation.is_contradicted is True
    assert len(evaluation.contradicting_evidence) == 1
    assert "exit code" in evaluation.reason or "failure" in evaluation.reason


# --- Scenario 8: Evidence from another call_id does not verify claim ---

def test_scenario_8_evidence_from_another_call_id_does_not_verify():
    """Scenario 8: Evidence referencing call_id 'c-foo' does not verify a claim for 'c-bar'."""
    store = _make_store_with_call_and_result(
        trace_id="tr-call-isolation",
        call_id="c-foo",
        tool_name="linter",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-bar",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Linter for bar succeeded",
        trace_id="tr-call-isolation",
        call_id="c-bar",  # Different call ID
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.UNVERIFIED
    assert evaluation.is_unverified is True
    assert len(evaluation.supporting_evidence) == 0


# --- Scenario 9: Evidence from another trace does not verify claim ---

def test_scenario_9_evidence_from_another_trace_does_not_verify():
    """Scenario 9: Evidence from trace 'tr-other' does not satisfy a claim scoped to 'tr-target'."""
    store = _make_store_with_call_and_result(
        trace_id="tr-other",
        call_id="c-same-id",
        tool_name="tester",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-target-trace",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Target trace test succeeded",
        trace_id="tr-target",  # Different trace ID
        call_id="c-same-id",
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.verdict == ClaimVerdict.UNVERIFIED
    assert evaluation.is_unverified is True


# --- Scenario 10: TracePointer resolves to exact supporting event ---

def test_scenario_10_trace_pointer_resolves_to_exact_event():
    """Scenario 10: An EvidenceRef pointer accurately resolves to the original TraceEvent in TraceStore."""
    store = _make_store_with_call_and_result(
        trace_id="tr-res-ptr",
        call_id="c-ptr-1",
        tool_name="formatter",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-ptr",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Formatter succeeded",
        trace_id="tr-res-ptr",
        call_id="c-ptr-1",
    )
    evaluation = gate.evaluate(claim, store)

    assert evaluation.is_verified is True
    ref = evaluation.supporting_evidence[0]
    resolved_event = gate.graph.resolve_pointer(ref.trace_pointer, store)

    assert resolved_event is not None
    assert resolved_event.event_id == ref.event_id
    assert resolved_event.trace_id == "tr-res-ptr"
    assert resolved_event.tool_result is not None
    assert resolved_event.tool_result.call_id == "c-ptr-1"


# --- Scenario 11: One evidence event supports multiple independent claims ---

def test_scenario_11_one_evidence_event_supports_multiple_claims():
    """Scenario 11: A single tool result can independently support multiple distinct claims."""
    store = _make_store_with_call_and_result(
        trace_id="tr-multi",
        call_id="c-multi-1",
        tool_name="pytest",
        cmd="pytest tests/",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
        output="passed",
    )
    gate = EvidenceGate()

    claim1 = Claim(
        claim_id="clm-multi-tool",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="pytest tool completed successfully",
        trace_id="tr-multi",
        call_id="c-multi-1",
    )
    claim2 = Claim(
        claim_id="clm-multi-cmd",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="pytest command returned 0",
        trace_id="tr-multi",
        call_id="c-multi-1",
    )
    claim3 = Claim(
        claim_id="clm-multi-tests",
        claim_type=ClaimType.TESTS_PASSED,
        description="pytest test suite passed",
        trace_id="tr-multi",
        call_id="c-multi-1",
    )

    evals = gate.evaluate_many([claim1, claim2, claim3], store)
    assert len(evals) == 3
    assert all(e.is_verified for e in evals)

    # All 3 evaluations point to the same underlying event
    res_event_id = "evt-c-multi-1-res"
    for e in evals:
        assert len(e.supporting_evidence) == 1
        assert e.supporting_evidence[0].event_id == res_event_id


# --- Scenario 12: Claim / Evaluation JSON round-trip ---

def test_scenario_12_claim_evaluation_json_round_trip():
    """Scenario 12: Claim and ClaimEvaluation serialize to JSON and deserialize identically."""
    store = _make_store_with_call_and_result(
        trace_id="tr-json",
        call_id="c-json-1",
        tool_name="compiler",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-json-round-trip",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="Compiler exited with 0",
        trace_id="tr-json",
        call_id="c-json-1",
        expected_exit_code=0,
        metadata={"build_env": "linux-x86_64"},
    )
    eval_result = gate.evaluate(claim, store)

    json_str = eval_result.model_dump_json()
    reconstructed = ClaimEvaluation.model_validate_json(json_str)

    assert reconstructed == eval_result
    assert reconstructed.verdict == ClaimVerdict.VERIFIED
    assert reconstructed.claim.metadata["build_env"] == "linux-x86_64"
    assert reconstructed.supporting_evidence[0].call_id == "c-json-1"


# --- Scenario 13: Graph reverse lookup evidence -> claims ---

def test_scenario_13_graph_reverse_lookup():
    """Scenario 13: EvidenceGraph supports querying which claims cite a given evidence event."""
    store = _make_store_with_call_and_result(
        trace_id="tr-lookup",
        call_id="c-lookup-1",
        tool_name="migrator",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()
    c1 = Claim(
        claim_id="clm-migration-1",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Migration tool ran",
        trace_id="tr-lookup",
        call_id="c-lookup-1",
    )
    c2 = Claim(
        claim_id="clm-migration-2",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="Migration exited zero",
        trace_id="tr-lookup",
        call_id="c-lookup-1",
    )

    gate.evaluate_many([c1, c2], store)

    # Reverse lookup by event ID
    target_event_id = "evt-c-lookup-1-res"
    citing_claims = gate.graph.get_claims_citing_evidence(target_event_id)
    assert citing_claims == ("clm-migration-1", "clm-migration-2")

    # Scoped lookup with trace_id
    citing_scoped = gate.graph.get_claims_citing_evidence(target_event_id, trace_id="tr-lookup")
    assert citing_scoped == ("clm-migration-1", "clm-migration-2")

    # Unreferenced event returns empty tuple
    assert gate.graph.get_claims_citing_evidence("non-existent-event") == ()


# --- Scenario 14: Contradictory evidence dominates support for same execution ---

def test_scenario_14_contradictory_evidence_dominates_support():
    """Scenario 14: Contradiction strictly dominates support for the same claim target / execution.

    Tests both:
    1. Direct verdict determination: when both supporting and contradicting evidence are present,
       CONTRADICTED strictly wins.
    2. End-to-end trace evaluation: where a file target has both supporting (creation) and
       contradicting (deletion) events in trace history.
    """
    # 1. Direct verdict determination rule check
    sup_ref = EvidenceRef(
        trace_pointer=TracePointer(trace_id="tr-conflict", event_id="evt-ok"),
        relation=EvidenceRelation.SUPPORTS,
        reason="Creation succeeded",
    )
    con_ref = EvidenceRef(
        trace_pointer=TracePointer(trace_id="tr-conflict", event_id="evt-err"),
        relation=EvidenceRelation.CONTRADICTS,
        reason="Subsequent observation confirmed file missing",
    )
    verdict, reason = EvidenceGate.determine_verdict([sup_ref], [con_ref])
    assert verdict == ClaimVerdict.CONTRADICTED
    assert "CONTRADICTED" in reason

    # 2. End-to-end trace evaluation for same claim target
    store = TraceStore()
    tc1 = ToolCall(call_id="c-write-f", tool_name="file_writer", arguments={"path": "temp.txt"})
    store.append(
        TraceEvent(
            event_id="evt-w-call",
            trace_id="tr-conflict",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc1,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-w-res",
            trace_id="tr-conflict",
            sequence=1,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-w-call",
            payload=ToolResult(
                call_id="c-write-f",
                status=ToolResultStatus.SUCCESS,
                output={"created_paths": ["temp.txt"]},
            ),
        )
    )
    tc2 = ToolCall(call_id="c-del-f", tool_name="file_deleter", arguments={"path": "temp.txt"})
    store.append(
        TraceEvent(
            event_id="evt-d-call",
            trace_id="tr-conflict",
            sequence=2,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc2,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-d-res",
            trace_id="tr-conflict",
            sequence=3,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-d-call",
            payload=ToolResult(
                call_id="c-del-f",
                status=ToolResultStatus.SUCCESS,
                output={"missing_paths": ["temp.txt"]},
            ),
        )
    )

    gate = EvidenceGate()
    claim_file = Claim(
        claim_id="clm-file-conflict",
        claim_type=ClaimType.FILE_EXISTS,
        description="temp.txt exists",
        trace_id="tr-conflict",
        target_path="temp.txt",
    )
    evaluation = gate.evaluate(claim_file, store)

    assert evaluation.verdict == ClaimVerdict.CONTRADICTED
    assert evaluation.is_contradicted is True
    assert len(evaluation.supporting_evidence) == 1
    assert len(evaluation.contradicting_evidence) == 1
    assert "CONTRADICTED" in evaluation.reason


# --- Scenario 15: FILE_EXISTS claim verification ---

def test_scenario_15_file_exists_claim_verification():
    """Scenario 15: FILE_EXISTS claim is verified when tool result reports created file, unverified otherwise."""
    store = TraceStore()
    tc = ToolCall(call_id="c-write", tool_name="file_writer", arguments={"path": "out.txt"})
    store.append(
        TraceEvent(
            event_id="evt-write-call",
            trace_id="tr-files",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-write-res",
            trace_id="tr-files",
            sequence=1,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-write-call",
            payload=ToolResult(
                call_id="c-write",
                status=ToolResultStatus.SUCCESS,
                output={"files": ["out.txt", "schema.sql"]},
                exit_code=0,
            ),
        )
    )

    gate = EvidenceGate()

    # Claim for out.txt -> VERIFIED
    claim_out = Claim(
        claim_id="clm-out-file",
        claim_type=ClaimType.FILE_EXISTS,
        description="out.txt exists",
        trace_id="tr-files",
        target_path="out.txt",
    )
    eval_out = gate.evaluate(claim_out, store)
    assert eval_out.verdict == ClaimVerdict.VERIFIED
    assert eval_out.is_verified is True

    # Claim for missing file -> UNVERIFIED
    claim_missing = Claim(
        claim_id="clm-missing-file",
        claim_type=ClaimType.FILE_EXISTS,
        description="nonexistent.txt exists",
        trace_id="tr-files",
        target_path="nonexistent.txt",
    )
    eval_missing = gate.evaluate(claim_missing, store)
    assert eval_missing.verdict == ClaimVerdict.UNVERIFIED
    assert eval_missing.is_unverified is True


# --- Regression Tests for Main Agent Review Blockers ---

def test_generic_claim_never_verified_by_evidence_gate():
    """GENERIC claim type must never be VERIFIED by deterministic EvidenceGate."""
    store = _make_store_with_call_and_result(
        trace_id="tr-generic",
        call_id="c-gen-1",
        tool_name="worker",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-generic-prose",
        claim_type=ClaimType.GENERIC,
        description="The code architecture is robust and fully optimal",
        trace_id="tr-generic",
        call_id="c-gen-1",
    )
    evaluation = gate.evaluate(claim, store)
    assert evaluation.verdict == ClaimVerdict.UNVERIFIED
    assert evaluation.is_unverified is True
    assert "GENERIC" in evaluation.reason


def test_execution_claim_requires_trace_id_and_selectors():
    """Execution claims missing trace_id or selectors must return UNVERIFIED without querying all traces."""
    store = _make_store_with_call_and_result(
        trace_id="tr-scoped",
        call_id="c-scoped-1",
        tool_name="tester",
        status=ToolResultStatus.SUCCESS,
        exit_code=0,
    )
    gate = EvidenceGate()

    # Missing trace_id
    claim_no_trace = Claim(
        claim_id="clm-no-trace",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Tester succeeded without trace",
        call_id="c-scoped-1",
    )
    eval_no_trace = gate.evaluate(claim_no_trace, store)
    assert eval_no_trace.verdict == ClaimVerdict.UNVERIFIED
    assert "must specify a trace_id" in eval_no_trace.reason

    # Missing all selectors
    claim_no_sel = Claim(
        claim_id="clm-no-selectors",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Tester succeeded without selectors",
        trace_id="tr-scoped",
    )
    eval_no_sel = gate.evaluate(claim_no_sel, store)
    assert eval_no_sel.verdict == ClaimVerdict.UNVERIFIED
    assert "lacks deterministic execution selectors" in eval_no_sel.reason


def test_ambiguous_execution_claim_returns_unverified():
    """When selectors match multiple executions in the trace, claim is UNVERIFIED due to ambiguity."""
    store = TraceStore()
    for i in (1, 2):
        tc = ToolCall(call_id=f"c-ambig-{i}", tool_name="worker", arguments={"task": f"step-{i}"})
        store.append(
            TraceEvent(
                event_id=f"evt-call-{i}",
                trace_id="tr-ambig",
                sequence=2 * (i - 1),
                actor=ActorKind.AGENT,
                event_kind=EventKind.TOOL_CALL,
                payload=tc,
            )
        )
        store.append(
            TraceEvent(
                event_id=f"evt-res-{i}",
                trace_id="tr-ambig",
                sequence=2 * (i - 1) + 1,
                actor=ActorKind.TOOL,
                event_kind=EventKind.TOOL_RESULT,
                parent_id=f"evt-call-{i}",
                payload=ToolResult(call_id=f"c-ambig-{i}", status=ToolResultStatus.SUCCESS, exit_code=0),
            )
        )

    gate = EvidenceGate()
    claim = Claim(
        claim_id="clm-ambig",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Worker task succeeded",
        trace_id="tr-ambig",
        tool_name="worker",  # Matches both c-ambig-1 and c-ambig-2
    )
    evaluation = gate.evaluate(claim, store)
    assert evaluation.verdict == ClaimVerdict.UNVERIFIED
    assert evaluation.is_unverified is True
    assert "Ambiguous claim" in evaluation.reason


def test_conjunctive_selectors_must_all_match():
    """call_id, tool_name, and command must all match conjunctively on the same ToolCall."""
    store = TraceStore()
    tc = ToolCall(call_id="c-conj-1", tool_name="bash", arguments={"cmd": "pytest -v"})
    store.append(
        TraceEvent(
            event_id="evt-conj-call",
            trace_id="tr-conj",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-conj-res",
            trace_id="tr-conj",
            sequence=1,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-conj-call",
            payload=ToolResult(call_id="c-conj-1", status=ToolResultStatus.SUCCESS, exit_code=0),
        )
    )

    gate = EvidenceGate()

    # Mismatch tool_name
    c_bad_tool = Claim(
        claim_id="clm-bad-tool",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="Test ran on git",
        trace_id="tr-conj",
        call_id="c-conj-1",
        tool_name="git",  # does not match bash
    )
    eval_bad_tool = gate.evaluate(c_bad_tool, store)
    assert eval_bad_tool.verdict == ClaimVerdict.UNVERIFIED
    assert "does not match" in eval_bad_tool.reason

    # Mismatch command
    c_bad_cmd = Claim(
        claim_id="clm-bad-cmd",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="Test ran flake8",
        trace_id="tr-conj",
        call_id="c-conj-1",
        tool_name="bash",
        command="flake8",  # does not match pytest
    )
    eval_bad_cmd = gate.evaluate(c_bad_cmd, store)
    assert eval_bad_cmd.verdict == ClaimVerdict.UNVERIFIED
    assert "do not match" in eval_bad_cmd.reason

    # All 3 match conjunctively -> VERIFIED
    c_good = Claim(
        claim_id="clm-good-all",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="Test ran pytest on bash",
        trace_id="tr-conj",
        call_id="c-conj-1",
        tool_name="bash",
        command="pytest",
    )
    eval_good = gate.evaluate(c_good, store)
    assert eval_good.verdict == ClaimVerdict.VERIFIED
    assert eval_good.is_verified is True


def test_file_exists_structured_evidence_only():
    """FILE_EXISTS only accepts explicit structured evidence; rejects plain text and unrelated observations."""
    store = TraceStore()
    tc1 = ToolCall(call_id="c-log", tool_name="logger", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-log-call",
            trace_id="tr-file-struct",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc1,
        )
    )
    # Plain text output mentioning the target file path
    store.append(
        TraceEvent(
            event_id="evt-log-res",
            trace_id="tr-file-struct",
            sequence=1,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-log-call",
            payload=ToolResult(
                call_id="c-log",
                status=ToolResultStatus.SUCCESS,
                output="Log text: generated report at /data/report.pdf successfully.",
                exit_code=0,
            ),
        )
    )
    # Output with exists=False for another path
    tc2 = ToolCall(call_id="c-stat", tool_name="stat", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-stat-call",
            trace_id="tr-file-struct",
            sequence=2,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc2,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-stat-res",
            trace_id="tr-file-struct",
            sequence=3,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-stat-call",
            payload=ToolResult(
                call_id="c-stat",
                status=ToolResultStatus.SUCCESS,
                output={"path": "/data/other.txt", "exists": False},
                exit_code=0,
            ),
        )
    )

    gate = EvidenceGate()

    # 1. Plain text cannot verify /data/report.pdf -> UNVERIFIED
    c_pdf = Claim(
        claim_id="clm-pdf",
        claim_type=ClaimType.FILE_EXISTS,
        description="report.pdf exists",
        trace_id="tr-file-struct",
        target_path="/data/report.pdf",
    )
    eval_pdf = gate.evaluate(c_pdf, store)
    assert eval_pdf.verdict == ClaimVerdict.UNVERIFIED
    assert eval_pdf.is_unverified is True

    # 2. {"path": "/data/other.txt", "exists": False} must not contradict /data/report.pdf
    assert len(eval_pdf.contradicting_evidence) == 0

    # 3. Exact target with exists=True -> VERIFIED
    tc3 = ToolCall(call_id="c-probe-ok", tool_name="probe", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-probe-ok-call",
            trace_id="tr-file-struct",
            sequence=4,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc3,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-probe-ok-res",
            trace_id="tr-file-struct",
            sequence=5,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-probe-ok-call",
            payload=ToolResult(
                call_id="c-probe-ok",
                status=ToolResultStatus.SUCCESS,
                output={"path": "/data/report.pdf", "exists": True},
                exit_code=0,
            ),
        )
    )
    eval_pdf_verified = gate.evaluate(c_pdf, store)
    assert eval_pdf_verified.verdict == ClaimVerdict.VERIFIED
    assert eval_pdf_verified.is_verified is True

    # 4. Exact target with exists=False -> CONTRADICTED
    c_other = Claim(
        claim_id="clm-other",
        claim_type=ClaimType.FILE_EXISTS,
        description="other.txt exists",
        trace_id="tr-file-struct",
        target_path="/data/other.txt",
    )
    eval_other = gate.evaluate(c_other, store)
    assert eval_other.verdict == ClaimVerdict.CONTRADICTED
    assert eval_other.is_contradicted is True

    # 5. Explicit missing_paths containing target -> CONTRADICTED
    tc_miss = ToolCall(call_id="c-miss", tool_name="cleaner", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-miss-call",
            trace_id="tr-file-struct",
            sequence=6,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc_miss,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-miss-res",
            trace_id="tr-file-struct",
            sequence=7,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-miss-call",
            payload=ToolResult(
                call_id="c-miss",
                status=ToolResultStatus.SUCCESS,
                output={"missing_paths": ["/data/deleted.txt"]},
                exit_code=0,
            ),
        )
    )
    c_del = Claim(
        claim_id="clm-deleted",
        claim_type=ClaimType.FILE_EXISTS,
        description="deleted.txt exists",
        trace_id="tr-file-struct",
        target_path="/data/deleted.txt",
    )
    eval_del = gate.evaluate(c_del, store)
    assert eval_del.verdict == ClaimVerdict.CONTRADICTED
    assert eval_del.is_contradicted is True

    # 6. Tool result with ERROR status must not verify existence even if created_paths is present
    tc4 = ToolCall(call_id="c-fail-write", tool_name="writer", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-fail-w-call",
            trace_id="tr-file-struct",
            sequence=8,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc4,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-fail-w-res",
            trace_id="tr-file-struct",
            sequence=9,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-fail-w-call",
            payload=ToolResult(
                call_id="c-fail-write",
                status=ToolResultStatus.ERROR,
                output={"created_paths": ["/data/failed_out.txt"]},
                error="Disk quota exceeded",
            ),
        )
    )
    c_failed = Claim(
        claim_id="clm-failed",
        claim_type=ClaimType.FILE_EXISTS,
        description="failed_out.txt exists",
        trace_id="tr-file-struct",
        target_path="/data/failed_out.txt",
    )
    eval_failed = gate.evaluate(c_failed, store)
    assert eval_failed.verdict == ClaimVerdict.UNVERIFIED
    assert eval_failed.is_unverified is True


def test_evidence_graph_update_clears_stale_reverse_edges():
    """Updating a claim in EvidenceGraph must purge old reverse edges before adding new ones."""
    graph = EvidenceGraph()
    claim = Claim(
        claim_id="clm-dynamic",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Dynamic claim",
        trace_id="tr-dyn",
        call_id="c-dyn-1",
    )

    # First evaluation citing evt-1
    ref1 = EvidenceRef(
        trace_pointer=TracePointer(trace_id="tr-dyn", event_id="evt-1"),
        relation=EvidenceRelation.SUPPORTS,
        call_id="c-dyn-1",
    )
    eval1 = ClaimEvaluation(
        claim=claim,
        verdict=ClaimVerdict.VERIFIED,
        supporting_evidence=(ref1,),
        contradicting_evidence=(),
        reason="Supported by evt-1",
    )
    graph.add_evaluation(eval1)

    assert graph.get_claims_citing_evidence("evt-1") == ("clm-dynamic",)
    assert graph.get_claims_citing_evidence("evt-2") == ()

    # Re-evaluate / update claim to cite evt-2 instead
    ref2 = EvidenceRef(
        trace_pointer=TracePointer(trace_id="tr-dyn", event_id="evt-2"),
        relation=EvidenceRelation.SUPPORTS,
        call_id="c-dyn-2",
    )
    eval2 = ClaimEvaluation(
        claim=claim,
        verdict=ClaimVerdict.VERIFIED,
        supporting_evidence=(ref2,),
        contradicting_evidence=(),
        reason="Supported by evt-2",
    )
    graph.add_evaluation(eval2)

    # evt-1 must no longer reverse-link to clm-dynamic
    assert graph.get_claims_citing_evidence("evt-1") == ()
    assert graph.get_claims_citing_evidence("evt-1", trace_id="tr-dyn") == ()

    # evt-2 must now reverse-link to clm-dynamic
    assert graph.get_claims_citing_evidence("evt-2") == ("clm-dynamic",)
    assert graph.get_claims_citing_evidence("evt-2", trace_id="tr-dyn") == ("clm-dynamic",)

