"""Tests for runtime domain models, serialization, and container immutability."""

import json
import pytest
from pydantic import ValidationError

from agentcontract.common.immutable import FrozenDict
from agentcontract.evidence.models import Claim, ClaimEvaluation, ClaimType, ClaimVerdict
from agentcontract.guard.models import Action, ActionKind, DecisionKind, GuardDecision
from agentcontract.runtime.exceptions import RuntimeValidationError
from agentcontract.runtime.models import (
    IdGenerator,
    RuntimeExecutionResult,
    ToolExecutionOutcome,
    VerificationResult,
)
from agentcontract.trace.models import (
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TracePointer,
)


def test_tool_execution_outcome_constructors_and_properties() -> None:
    # 1. Success outcome
    succ = ToolExecutionOutcome.success(
        output={"status": "ok", "items": [1, 2]},
        changed_paths=["/tmp/a.txt"],
        accessed_paths=["/tmp/b.txt"],
        exit_code=0,
        duration_ms=12.5,
        metadata={"worker": "test-1"},
    )
    assert succ.status == ToolResultStatus.SUCCESS
    assert isinstance(succ.output, FrozenDict)
    assert succ.output["status"] == "ok"
    assert succ.output["items"] == (1, 2)
    assert succ.changed_paths == ("/tmp/a.txt",)
    assert succ.accessed_paths == ("/tmp/b.txt",)
    assert succ.exit_code == 0
    assert succ.duration_ms == 12.5
    assert succ.metadata["worker"] == "test-1"

    # 2. Error outcome
    err = ToolExecutionOutcome.failed(
        error="Permission denied",
        exit_code=13,
        duration_ms=5.0,
    )
    assert err.status == ToolResultStatus.ERROR
    assert err.error == "Permission denied"
    assert err.exit_code == 13

    # 3. Timeout outcome
    tout = ToolExecutionOutcome.timeout(duration_ms=5000.0)
    assert tout.status == ToolResultStatus.TIMEOUT
    assert "timed out" in tout.error.lower()

    # 4. Cancelled outcome
    canc = ToolExecutionOutcome.cancelled(duration_ms=1.0)
    assert canc.status == ToolResultStatus.CANCELLED
    assert "cancelled" in canc.error.lower()

    # 5. from_tool_result
    tr = ToolResult(
        call_id="call-99",
        status=ToolResultStatus.SUCCESS,
        output="done",
        exit_code=0,
    )
    from_tr = ToolExecutionOutcome.from_tool_result(
        tr,
        changed_paths=["out.log"],
        tool_name="my_tool",
    )
    assert from_tr.status == ToolResultStatus.SUCCESS
    assert from_tr.output == "done"
    assert from_tr.changed_paths == ("out.log",)
    assert from_tr.tool_name == "my_tool"


def test_tool_execution_outcome_rejects_unordered_sets() -> None:
    with pytest.raises(RuntimeValidationError, match="ordered sequence"):
        ToolExecutionOutcome(
            changed_paths={"/tmp/a.txt"},  # type: ignore[arg-type]
        )

    with pytest.raises(RuntimeValidationError, match="ordered sequence"):
        ToolExecutionOutcome(
            accessed_paths={"/tmp/b.txt"},  # type: ignore[arg-type]
        )


def test_id_generator_modes() -> None:
    # Deterministic generator
    det_gen = IdGenerator(prefix="test_", deterministic=True)
    assert det_gen.new_event_id() == "test_evt_0001"
    assert det_gen.new_event_id() == "test_evt_0002"
    assert det_gen.new_call_id() == "test_call_0001"
    assert det_gen.new_trace_id() == "test_trace_0001"
    assert det_gen.new_session_id() == "test_session_0001"

    # Default UUID generator
    rnd_gen = IdGenerator()
    id1 = rnd_gen.new_event_id()
    id2 = rnd_gen.new_event_id()
    assert id1.startswith("evt_")
    assert id2.startswith("evt_")
    assert id1 != id2


def test_runtime_execution_result_properties_and_immutability() -> None:
    action = Action(tool_name="bash", payload={"cmd": "ls"})
    pre_dec = GuardDecision(
        decision=DecisionKind.ALLOW,
        action=action,
    )
    tc = ToolCall(call_id="c-1", tool_name="bash")
    tr = ToolResult(call_id="c-1", status=ToolResultStatus.SUCCESS, output="files")
    post_dec = GuardDecision(
        decision=DecisionKind.ALLOW,
        action=action,
    )
    call_ptr = TracePointer(trace_id="t1", event_id="e1")
    res_ptr = TracePointer(trace_id="t1", event_id="e2")

    res = RuntimeExecutionResult(
        action=action,
        pre_decision=pre_dec,
        executed=True,
        tool_call=tc,
        tool_result=tr,
        post_decision=post_dec,
        tool_call_event_pointer=call_ptr,
        tool_result_event_pointer=res_ptr,
    )

    assert res.is_allowed is True
    assert res.is_blocked is False
    assert res.is_post_blocked is False
    assert res.is_warned is False
    assert res.is_success is True
    assert res.trace_pointers == (call_ptr, res_ptr)

    # Immutability
    with pytest.raises(ValidationError):
        res.executed = False  # type: ignore[misc]


def test_verification_result_container_methods_and_properties() -> None:
    c1 = Claim(
        claim_id="c1",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="c1 desc",
        trace_id="t1",
    )
    c2 = Claim(
        claim_id="c2",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="c2 desc",
        trace_id="t1",
    )

    ev1 = ClaimEvaluation(
        claim=c1,
        verdict=ClaimVerdict.VERIFIED,
        reason="ok",
    )
    ev2 = ClaimEvaluation(
        claim=c2,
        verdict=ClaimVerdict.CONTRADICTED,
        reason="failed exit code",
    )

    vr = VerificationResult(evaluations=(ev1, ev2))

    assert len(vr) == 2
    assert vr[0] == ev1
    assert vr[1] == ev2
    assert list(vr) == [ev1, ev2]
    assert vr.all_verified is False
    assert vr.has_contradictions is True
    assert vr.has_unverified is False
    assert vr.by_claim_id["c1"] == ev1
    assert vr.get("c2") == ev2
    assert vr.get("nonexistent") is None

    # All verified case
    vr_all = VerificationResult(evaluations=(ev1,))
    assert vr_all.all_verified is True
    assert vr_all.has_contradictions is False
    assert vr_all.has_unverified is False

    # Empty case
    vr_empty = VerificationResult(evaluations=())
    assert len(vr_empty) == 0
    assert vr_empty.all_verified is False


def test_runtime_serialization_round_trip() -> None:
    action = Action(
        tool_name="python",
        action_kind=ActionKind.COMMAND_EXEC,
        payload={"script": "print('hello')"},
        context=FrozenDict({"env": "test"}),
    )
    pre_dec = GuardDecision(
        decision=DecisionKind.WARN,
        action=action,
        matched_constraint_ids=("C-1",),
        violating_constraint_ids=("C-1",),
        reasons=("Soft warning on script execution",),
    )
    tc = ToolCall(call_id="call-42", tool_name="python", arguments=FrozenDict({"script": "print('hello')"}))
    tr = ToolResult(
        call_id="call-42",
        status=ToolResultStatus.SUCCESS,
        output={"stdout": "hello\n"},
        exit_code=0,
        duration_ms=45.2,
    )
    post_dec = GuardDecision(
        decision=DecisionKind.ALLOW,
        action=action,
        reasons=("Action allowed post-check",),
    )
    call_ptr = TracePointer(trace_id="t-100", event_id="evt-1")
    res_ptr = TracePointer(trace_id="t-100", event_id="evt-2")

    exec_res = RuntimeExecutionResult(
        action=action,
        pre_decision=pre_dec,
        executed=True,
        tool_call=tc,
        tool_result=tr,
        post_decision=post_dec,
        tool_call_event_pointer=call_ptr,
        tool_result_event_pointer=res_ptr,
    )

    # JSON round trip for RuntimeExecutionResult
    json_str = exec_res.model_dump_json()
    parsed_dict = json.loads(json_str)
    assert parsed_dict["executed"] is True
    assert parsed_dict["tool_result"]["status"] == "SUCCESS"

    restored_exec = RuntimeExecutionResult.model_validate_json(json_str)
    assert restored_exec == exec_res
    assert restored_exec.is_warned is True
    assert restored_exec.is_success is True

    # JSON round trip for VerificationResult
    claim = Claim(
        claim_id="clm-1",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="test tool succ",
        trace_id="t-100",
        call_id="call-42",
    )
    eval_res = ClaimEvaluation(
        claim=claim,
        verdict=ClaimVerdict.VERIFIED,
        reason="Verified by call-42 result",
    )
    verif = VerificationResult(evaluations=(eval_res,))
    verif_json = verif.model_dump_json()
    restored_verif = VerificationResult.model_validate_json(verif_json)
    assert restored_verif == verif
    assert restored_verif.all_verified is True


def test_top_level_package_exports_runtime() -> None:
    import agentcontract

    assert hasattr(agentcontract, "AgentContractRuntime")
    assert hasattr(agentcontract, "ToolExecutionOutcome")
    assert hasattr(agentcontract, "RuntimeExecutionResult")
    assert hasattr(agentcontract, "VerificationResult")
    assert hasattr(agentcontract, "IdGenerator")
    assert hasattr(agentcontract, "AgentContractRuntimeError")
    assert hasattr(agentcontract, "RuntimeValidationError")
    assert hasattr(agentcontract, "ToolExecutionError")
    assert hasattr(agentcontract, "ToolExecutor")
