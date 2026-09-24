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
    """Scenario 14: When both supporting and contradictory evidence exist, contradiction wins."""
    # Construct a claim evaluated with custom contradictory evidence
    claim = Claim(
        claim_id="clm-contradiction",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Action completed successfully",
        trace_id="tr-conflict",
    )
    sup_ref = EvidenceRef(
        trace_pointer=TracePointer(trace_id="tr-conflict", event_id="evt-ok"),
        relation=EvidenceRelation.SUPPORTS,
        reason="Partial step succeeded",
    )
    con_ref = EvidenceRef(
        trace_pointer=TracePointer(trace_id="tr-conflict", event_id="evt-err"),
        relation=EvidenceRelation.CONTRADICTS,
        reason="Final step threw fatal exception",
    )

    # EvidenceGate evaluate with mixed results from matching calls
    store = TraceStore()
    tc1 = ToolCall(call_id="call-step-1", tool_name="pipeline", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-call-1",
            trace_id="tr-conflict",
            sequence=0,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc1,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-ok",
            trace_id="tr-conflict",
            sequence=1,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-call-1",
            payload=ToolResult(call_id="call-step-1", status=ToolResultStatus.SUCCESS, exit_code=0),
        )
    )

    tc2 = ToolCall(call_id="call-step-2", tool_name="pipeline", arguments={})
    store.append(
        TraceEvent(
            event_id="evt-call-2",
            trace_id="tr-conflict",
            sequence=2,
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tc2,
        )
    )
    store.append(
        TraceEvent(
            event_id="evt-err",
            trace_id="tr-conflict",
            sequence=3,
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id="evt-call-2",
            payload=ToolResult(call_id="call-step-2", status=ToolResultStatus.ERROR, error="Failed"),
        )
    )

    gate = EvidenceGate()
    # Claim targets tool_name="pipeline" without specific call_id -> finds both step 1 and step 2
    claim_pipeline = Claim(
        claim_id="clm-pipeline",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Pipeline succeeded",
        trace_id="tr-conflict",
        tool_name="pipeline",
    )
    evaluation = gate.evaluate(claim_pipeline, store)

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
