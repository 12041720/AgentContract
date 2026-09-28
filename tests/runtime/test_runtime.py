"""End-to-end integration tests for AgentContractRuntime covering all product scenarios."""

from typing import Any
import pytest

from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.evidence.models import (
    Claim,
    ClaimType,
    ClaimVerdict,
)
from agentcontract.guard.models import (
    Action,
    ActionKind,
    DecisionKind,
)
from agentcontract.runtime.exceptions import RuntimeValidationError
from agentcontract.runtime.models import (
    IdGenerator,
    ToolExecutionOutcome,
)
from agentcontract.runtime.session import AgentContractRuntime
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResultStatus,
)


def _make_constraint(
    cid: str,
    name: str,
    strength: ConstraintStrength = ConstraintStrength.HARD,
    rule_effect: RuleEffect = RuleEffect.DENY,
    scope: ConstraintScope | None = None,
    compliance_scope: ConstraintScope | None = None,
) -> Constraint:
    return Constraint(
        id=cid,
        name=name,
        description=f"Rule {name}",
        strength=strength,
        rule_effect=rule_effect,
        scope=scope or ConstraintScope(),
        compliance_scope=compliance_scope,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )


# ---------------------------------------------------------------------------
# Scenario 1: Pre-action hard block
# ---------------------------------------------------------------------------
def test_scenario_1_pre_action_hard_block_prevents_execution() -> None:
    runtime = AgentContractRuntime()
    # HARD DENY on writing to production database config
    runtime.add_constraint(
        _make_constraint(
            cid="C-DB-BLOCK",
            name="Deny write to db credentials",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                actions=("write", "file_write"),
                paths=("/etc/db/credentials.json",),
            ),
        )
    )

    call_count = 0

    def executor(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        nonlocal call_count
        call_count += 1
        return ToolExecutionOutcome.success(output="written")

    action = Action(
        tool_name="file_writer",
        action_kind=ActionKind.FILE_WRITE,
        target_path="/etc/db/credentials.json",
        payload={"content": "secret"},
    )

    result = runtime.execute(action, executor)

    # 1. Runtime returns BLOCK
    assert result.is_blocked is True
    assert result.pre_decision.decision == DecisionKind.BLOCK
    assert "C-DB-BLOCK" in result.pre_decision.violating_constraint_ids

    # 2. Executor was NOT invoked
    assert result.executed is False
    assert call_count == 0
    assert result.tool_call is None
    assert result.tool_result is None
    assert result.post_decision is None

    # 3. Guard decision is traceable in TraceStore
    assert result.pre_guard_event_pointer is not None
    guard_event = runtime.trace_store.get(result.pre_guard_event_pointer.event_id)
    assert guard_event.event_kind == EventKind.GUARD_DECISION
    assert guard_event.actor == ActorKind.GUARD
    assert guard_event.sequence == 0


# ---------------------------------------------------------------------------
# Scenario 2: Allowed successful execution and claim verification
# ---------------------------------------------------------------------------
def test_scenario_2_allowed_successful_execution_and_claim_verification() -> None:
    runtime = AgentContractRuntime()
    # Constraint on a completely different path
    runtime.add_constraint(
        _make_constraint(
            cid="C-OTHER",
            name="Deny unrelated path",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(paths=("/var/log/secret.log",)),
        )
    )

    call_count = 0

    def executor(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        nonlocal call_count
        call_count += 1
        return ToolExecutionOutcome.success(
            output={"files": ["report.csv"], "bytes_written": 128},
            changed_paths=["/home/user/report.csv"],
            exit_code=0,
        )

    action = Action(
        tool_name="csv_exporter",
        action_kind=ActionKind.FILE_WRITE,
        target_path="/home/user/report.csv",
        payload={"format": "csv"},
    )

    result = runtime.execute(action, executor)

    # 1. Pre-check ALLOW
    assert result.pre_decision.decision == DecisionKind.ALLOW
    assert result.is_allowed is True
    assert result.is_blocked is False

    # 2. Tool invoked exactly once
    assert call_count == 1
    assert result.executed is True
    assert result.is_success is True

    # 3. Trace contains exactly one TOOL_CALL and one correlated TOOL_RESULT
    events = runtime.trace_store.list_events(runtime.trace_id)
    assert len(events) == 2
    assert events[0].event_kind == EventKind.TOOL_CALL
    assert events[1].event_kind == EventKind.TOOL_RESULT
    assert events[0].tool_call is not None
    assert events[1].tool_result is not None
    assert events[0].tool_call.call_id == events[1].tool_result.call_id
    assert events[1].parent_id == events[0].event_id

    # 4. Post-check ALLOW
    assert result.post_decision is not None
    assert result.post_decision.decision == DecisionKind.ALLOW

    # 5. Scoped completion claims verify
    c1 = Claim(
        claim_id="clm-succ-1",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="csv_exporter completed successfully",
        trace_id=runtime.trace_id,
        call_id=result.tool_call.call_id,
    )
    c2 = Claim(
        claim_id="clm-succ-2",
        claim_type=ClaimType.COMMAND_EXITED_ZERO,
        description="exit code was 0",
        trace_id=runtime.trace_id,
        call_id=result.tool_call.call_id,
    )

    verifications = runtime.verify_claims([c1, c2])
    assert verifications.all_verified is True
    assert verifications.has_contradictions is False
    assert verifications.has_unverified is False
    assert verifications.get("clm-succ-1").verdict == ClaimVerdict.VERIFIED
    assert verifications.get("clm-succ-2").verdict == ClaimVerdict.VERIFIED


# ---------------------------------------------------------------------------
# Scenario 3: Warning does not silently become block
# ---------------------------------------------------------------------------
def test_scenario_3_warning_does_not_silently_block() -> None:
    runtime = AgentContractRuntime()
    # SOFT rule produces WARN
    runtime.add_constraint(
        _make_constraint(
            cid="C-SOFT-WARN",
            name="Discourage tmp cleanup",
            strength=ConstraintStrength.SOFT,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                actions=("cleanup",),
            ),
        )
    )

    call_count = 0

    def executor(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        nonlocal call_count
        call_count += 1
        return ToolExecutionOutcome.success(output="cleaned")

    action = Action(
        tool_name="cleaner",
        operation="cleanup",
        payload={"target": "cache"},
    )

    result = runtime.execute(action, executor)

    # 1. Pre-decision is WARN
    assert result.pre_decision.decision == DecisionKind.WARN
    assert result.is_warned is True
    assert result.is_blocked is False

    # 2. Tool executed exactly once
    assert call_count == 1
    assert result.executed is True
    assert result.tool_result.status == ToolResultStatus.SUCCESS

    # 3. Warning is retained in result
    assert "C-SOFT-WARN" in result.pre_decision.violating_constraint_ids
    assert any("WARN:" in r for r in result.pre_decision.reasons)


# ---------------------------------------------------------------------------
# Scenario 4: Executor exception/failure recorded as ERROR ToolResult
# ---------------------------------------------------------------------------
def test_scenario_4_executor_exception_becomes_error_tool_result() -> None:
    runtime = AgentContractRuntime()

    def crashing_executor(action: Action, tool_call: Any) -> Any:
        raise OSError("Disk quota exceeded (simulated)")

    action = Action(
        tool_name="heavy_writer",
        action_kind=ActionKind.FILE_WRITE,
        payload={"size": 1000000},
    )

    result = runtime.execute(action, crashing_executor)

    # 1. Tool executed and runtime caught exception
    assert result.executed is True
    assert result.is_success is False
    assert result.tool_result is not None
    assert result.tool_result.status == ToolResultStatus.ERROR
    assert "OSError: Disk quota exceeded" in result.tool_result.error

    # 2. TOOL_RESULT trace event is recorded
    events = runtime.trace_store.list_events(runtime.trace_id)
    assert len(events) == 2
    res_evt = events[1]
    assert res_evt.event_kind == EventKind.TOOL_RESULT
    assert res_evt.tool_result.is_error is True

    # 3. Success claim is CONTRADICTED
    claim = Claim(
        claim_id="clm-fail",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="heavy_writer should have succeeded",
        trace_id=runtime.trace_id,
        call_id=result.tool_call.call_id,
    )
    verifs = runtime.verify_claims([claim])
    assert verifs.has_contradictions is True
    assert verifs.get("clm-fail").verdict == ClaimVerdict.CONTRADICTED


# ---------------------------------------------------------------------------
# Scenario 5: Post-action violation detected by SpecGuard
# ---------------------------------------------------------------------------
def test_scenario_5_post_action_violation_blocks_after_execution() -> None:
    runtime = AgentContractRuntime()
    # HARD DENY on writing to /etc/hosts
    runtime.add_constraint(
        _make_constraint(
            cid="C-HARD-HOSTS",
            name="Protect hosts file",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                actions=("file_write", "write"),
                paths=("/etc/hosts",),
            ),
        )
    )

    call_count = 0

    def sneaky_tool(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        nonlocal call_count
        call_count += 1
        # Action proposed a generic setup tool without path, but actually modified /etc/hosts!
        return ToolExecutionOutcome.success(
            output={"modified": ["/etc/hosts"]},
            changed_paths=["/etc/hosts"],
        )

    # Pre-action passes check (no prohibited path specified)
    action = Action(
        tool_name="network_setup",
        action_kind=ActionKind.TOOL_CALL,
        payload={"mode": "dns"},
    )

    result = runtime.execute(action, sneaky_tool)

    # 1. Pre-check was ALLOW
    assert result.pre_decision.decision == DecisionKind.ALLOW

    # 2. Tool did execute
    assert call_count == 1
    assert result.executed is True

    # 3. Post-action SpecGuard detected violation and produced BLOCK
    assert result.post_decision is not None
    assert result.post_decision.decision == DecisionKind.BLOCK
    assert result.is_post_blocked is True
    assert result.is_success is False
    assert "C-HARD-HOSTS" in result.post_decision.violating_constraint_ids

    # 4. Provenance points to actual observed execution event (TOOL_RESULT)
    assert result.post_decision.trace_pointer is not None
    assert result.post_decision.trace_pointer == result.tool_result_event_pointer

    # 5. Post guard decision event was recorded in trace
    assert result.post_guard_event_pointer is not None
    post_evt = runtime.trace_store.get(result.post_guard_event_pointer.event_id)
    assert post_evt.event_kind == EventKind.GUARD_DECISION
    assert post_evt.actor == ActorKind.GUARD
    assert post_evt.parent_id == result.tool_result_event_pointer.event_id


# ---------------------------------------------------------------------------
# Scenario 6: Unsupported or under-evidenced completion claims
# ---------------------------------------------------------------------------
def test_scenario_6_unsupported_completion_claims_remain_unverified() -> None:
    runtime = AgentContractRuntime()

    # Generic claim
    c_generic = Claim(
        claim_id="clm-gen",
        claim_type=ClaimType.GENERIC,
        description="The agent performed excellent reasoning",
        trace_id=runtime.trace_id,
    )

    # Claim without trace_id
    c_no_trace = Claim(
        claim_id="clm-no-trace",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Unscoped tool run",
        trace_id=None,
    )

    # Claim for non-existent call_id
    c_ghost_call = Claim(
        claim_id="clm-ghost",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="Ghost execution",
        trace_id=runtime.trace_id,
        call_id="call-does-not-exist",
    )

    results = runtime.verify_claims([c_generic, c_no_trace, c_ghost_call])

    assert results.all_verified is False
    assert results.has_unverified is True
    assert results.get("clm-gen").verdict == ClaimVerdict.UNVERIFIED
    assert results.get("clm-no-trace").verdict == ClaimVerdict.UNVERIFIED
    assert results.get("clm-ghost").verdict == ClaimVerdict.UNVERIFIED


# ---------------------------------------------------------------------------
# Scenario 7: Trace integrity across multiple runtime executions
# ---------------------------------------------------------------------------
def test_scenario_7_trace_integrity_across_multiple_executions() -> None:
    id_gen = IdGenerator(prefix="test_", deterministic=True)
    runtime = AgentContractRuntime(id_generator=id_gen)

    def simple_executor(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        return ToolExecutionOutcome.success(output=f"done {tool_call.tool_name}")

    # Execute 3 separate actions
    r1 = runtime.execute(Action(tool_name="tool_1"), simple_executor)
    r2 = runtime.execute(Action(tool_name="tool_2"), simple_executor)
    r3 = runtime.execute(Action(tool_name="tool_3"), simple_executor)

    assert r1.executed and r2.executed and r3.executed

    events = runtime.trace_store.list_events(runtime.trace_id)
    # Each executed action appends 1 TOOL_CALL and 1 TOOL_RESULT = 6 total events
    assert len(events) == 6

    # Verify monotonic sequences: 0, 1, 2, 3, 4, 5
    for idx, evt in enumerate(events):
        assert evt.sequence == idx

    # Verify tool call / result correlation and parent linkages
    assert events[1].parent_id == events[0].event_id
    assert events[1].tool_result.call_id == events[0].tool_call.call_id

    assert events[3].parent_id == events[2].event_id
    assert events[3].tool_result.call_id == events[2].tool_call.call_id

    assert events[5].parent_id == events[4].event_id
    assert events[5].tool_result.call_id == events[4].tool_call.call_id


# ---------------------------------------------------------------------------
# Scenario 8: Serialization of runtime execution and verification results
# ---------------------------------------------------------------------------
def test_scenario_8_runtime_serialization_round_trip() -> None:
    runtime = AgentContractRuntime()

    def my_tool(action: Action) -> ToolExecutionOutcome:
        return ToolExecutionOutcome.success(output={"value": 100})

    result = runtime.execute(
        tool_name="calculator",
        action_kind=ActionKind.TOOL_CALL,
        payload={"expr": "10 * 10"},
        executor=my_tool,
    )

    # 1. Serialize RuntimeExecutionResult
    json_str = result.model_dump_json()
    loaded_result = result.model_validate_json(json_str)
    assert loaded_result == result
    assert loaded_result.is_success is True

    # 2. Verify claims and serialize VerificationResult
    claim = Claim(
        claim_id="calc-claim",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="calculator worked",
        trace_id=runtime.trace_id,
        call_id=result.tool_call.call_id,
    )
    verifs = runtime.verify_claims([claim])
    verifs_json = verifs.model_dump_json()
    loaded_verifs = verifs.model_validate_json(verifs_json)
    assert loaded_verifs == verifs
    assert loaded_verifs.all_verified is True


# ---------------------------------------------------------------------------
# Additional coverage: flexible executor signatures and return types
# ---------------------------------------------------------------------------
def test_flexible_executor_signatures_and_return_types() -> None:
    runtime = AgentContractRuntime()

    # 1. Executor taking only ToolCall (must assert actual received type is ToolCall)
    def exec_tool_call(tc: ToolCall) -> str:
        assert isinstance(tc, ToolCall)
        assert not isinstance(tc, Action)
        return f"result for {tc.tool_name}"

    r1 = runtime.execute(Action(tool_name="t1"), exec_tool_call)
    assert r1.is_success is True
    assert r1.tool_result.output == "result for t1"

    # 2. Executor taking only Action (must assert actual received type is Action)
    def exec_action(act: Action) -> dict[str, Any]:
        assert isinstance(act, Action)
        assert not isinstance(act, ToolCall)
        return {"action_target": act.target_path, "status": "SUCCESS"}

    r2 = runtime.execute(Action(tool_name="t2", target_path="/path/x"), exec_action)
    assert r2.is_success is True
    assert r2.tool_result.output["action_target"] == "/path/x"

    # 3. Executor taking zero arguments
    def exec_zero() -> int:
        return 0

    r3 = runtime.execute(
        Action(tool_name="cmd", action_kind=ActionKind.COMMAND_EXEC),
        exec_zero,
    )
    assert r3.is_success is True
    assert r3.tool_result.exit_code == 0

    # 4. Executor returning non-zero int for COMMAND_EXEC
    def exec_fail_cmd() -> int:
        return 127

    r4 = runtime.execute(
        Action(tool_name="cmd_bad", action_kind=ActionKind.COMMAND_EXEC),
        exec_fail_cmd,
    )
    assert r4.is_success is False
    assert r4.tool_result.status == ToolResultStatus.ERROR
    assert r4.tool_result.exit_code == 127


def test_executor_internal_type_error_invoked_exactly_once() -> None:
    runtime = AgentContractRuntime()
    call_count = 0

    def bad_executor(action: Action, tool_call: ToolCall) -> Any:
        nonlocal call_count
        call_count += 1
        # Raise internal TypeError from executor body
        raise TypeError("simulated internal type error in executor logic")

    res = runtime.execute(Action(tool_name="failing_tool"), bad_executor)

    # 1. Executor invocation count must be EXACTLY 1 (no retries!)
    assert call_count == 1
    assert res.executed is True
    assert res.is_success is False
    assert res.tool_result is not None
    assert res.tool_result.status == ToolResultStatus.ERROR
    assert "TypeError: simulated internal type error" in res.tool_result.error

    # 2. Exactly one TOOL_CALL and one correlated TOOL_RESULT recorded in trace
    events = runtime.trace_store.list_events(runtime.trace_id)
    assert len(events) == 2
    assert events[0].event_kind == EventKind.TOOL_CALL
    assert events[1].event_kind == EventKind.TOOL_RESULT
    assert events[1].tool_result.is_error is True


def test_unsupported_signature_fails_before_execution() -> None:
    runtime = AgentContractRuntime()
    call_count = 0

    def bad_sig_executor(a: int, b: int, c: int) -> Any:
        nonlocal call_count
        call_count += 1
        return "never reached"

    res = runtime.execute(Action(tool_name="bad_sig_tool"), bad_sig_executor)

    # Executor must NEVER be called: executed must be False and call_count must be 0
    assert call_count == 0
    assert res.executed is False
    assert res.is_success is False
    assert res.post_decision is None
    assert res.tool_result is not None
    assert res.tool_result.status == ToolResultStatus.ERROR
    assert "ToolExecutionError" in res.tool_result.error or "cannot be called with candidate arguments" in res.tool_result.error


def test_executor_executed_flag_distinguishes_signature_failure_from_body_exception() -> None:
    """Regression test: executed=False when parameter binding fails before invocation;
    executed=True when function body actually runs and then raises an exception."""
    runtime = AgentContractRuntime()

    # Case A: Parameter resolution / signature validation fails BEFORE invocation
    sig_fail_count = 0

    def bad_sig_fn(x: int, y: int, z: int) -> Any:
        nonlocal sig_fail_count
        sig_fail_count += 1
        return "never called"

    res_a = runtime.execute(Action(tool_name="sig_fail_tool"), bad_sig_fn)
    assert sig_fail_count == 0
    assert res_a.executed is False
    assert res_a.post_decision is None
    assert res_a.is_success is False
    assert res_a.tool_result is not None
    assert res_a.tool_result.status == ToolResultStatus.ERROR

    # Case B: Executor entered function body and THEN raised an exception
    body_err_count = 0

    def body_err_fn(action: Action, tool_call: ToolCall) -> Any:
        nonlocal body_err_count
        body_err_count += 1
        raise RuntimeError("failed during execution in body")

    res_b = runtime.execute(Action(tool_name="body_err_tool"), body_err_fn)
    assert body_err_count == 1
    assert res_b.executed is True
    assert res_b.post_decision is not None
    assert res_b.is_success is False
    assert res_b.tool_result is not None
    assert res_b.tool_result.status == ToolResultStatus.ERROR
    assert "failed during execution in body" in str(res_b.tool_result.error)


def test_post_action_target_type_violation_blocks() -> None:
    runtime = AgentContractRuntime()

    # HARD DENY constraint on target_type="production_db"
    runtime.add_constraint(
        _make_constraint(
            cid="C-PROD-DB-BLOCK",
            name="Prohibit operations on production database",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                target_type="production_db",
            ),
        )
    )

    call_count = 0

    def sneaky_db_tool(action: Action, tool_call: ToolCall) -> ToolExecutionOutcome:
        nonlocal call_count
        call_count += 1
        # Pre-action was proposed with staging_db, but tool execution actually accessed production_db
        return ToolExecutionOutcome.success(
            output={"rows_modified": 42},
            target_type="production_db",
        )

    # Pre-action target_type is staging_db (not prohibited)
    action = Action(
        tool_name="db_migrator",
        action_kind=ActionKind.TOOL_CALL,
        target_type="staging_db",
    )

    res = runtime.execute(action, sneaky_db_tool)

    # 1. Pre-action was ALLOW
    assert res.pre_decision.decision == DecisionKind.ALLOW

    # 2. Tool did execute
    assert call_count == 1
    assert res.executed is True

    # 3. Post-action SpecGuard detected forbidden target_type and returned BLOCK
    assert res.post_decision is not None
    assert res.post_decision.decision == DecisionKind.BLOCK
    assert res.is_post_blocked is True
    assert res.is_success is False
    assert "C-PROD-DB-BLOCK" in res.post_decision.violating_constraint_ids

    # 4. Provenance points to the TOOL_RESULT event
    assert res.post_decision.trace_pointer == res.tool_result_event_pointer



def test_runtime_validation_errors() -> None:
    runtime = AgentContractRuntime()

    # Missing executor
    with pytest.raises(RuntimeValidationError, match="executor must be provided"):
        runtime.execute(Action(tool_name="tool"))

    # Missing action parameters
    with pytest.raises(RuntimeValidationError, match="Action instance or action parameters"):
        runtime.execute(executor=lambda: None)

    # Invalid id_generator
    with pytest.raises(RuntimeValidationError, match="Invalid id_generator type"):
        AgentContractRuntime(id_generator=12345)  # type: ignore[arg-type]

    # Set rejected for paths in execute()
    with pytest.raises(RuntimeValidationError, match="ordered sequence"):
        runtime.execute(tool_name="tool", paths={"/a", "/b"}, executor=lambda a, c: "ok")  # type: ignore[arg-type]


def test_record_all_guard_decisions_records_allow_and_warn() -> None:
    runtime = AgentContractRuntime(record_all_guard_decisions=True)

    def simple_tool(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        return ToolExecutionOutcome.success(output="ok")

    res = runtime.execute(Action(tool_name="test_tool"), simple_tool)
    assert res.is_success is True
    assert res.pre_guard_event_pointer is not None

    events = runtime.trace_store.list_events(runtime.trace_id)
    # With record_all_guard_decisions=True:
    # 1. GUARD_DECISION (pre_action ALLOW)
    # 2. TOOL_CALL
    # 3. TOOL_RESULT
    # 4. GUARD_DECISION (post_action ALLOW)
    assert len(events) == 4
    assert events[0].event_kind == EventKind.GUARD_DECISION
    assert events[1].event_kind == EventKind.TOOL_CALL
    assert events[2].event_kind == EventKind.TOOL_RESULT
    assert events[3].event_kind == EventKind.GUARD_DECISION


def test_timeout_and_cancelled_outcomes_contradict_success_claim() -> None:
    runtime = AgentContractRuntime()

    # Timeout execution
    def timeout_tool(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        return ToolExecutionOutcome.timeout(duration_ms=5000.0)

    res_timeout = runtime.execute(Action(tool_name="slow_tool"), timeout_tool)
    assert res_timeout.tool_result.status == ToolResultStatus.TIMEOUT
    assert res_timeout.is_success is False

    c_timeout = Claim(
        claim_id="clm-timeout",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="slow tool should have succeeded",
        trace_id=runtime.trace_id,
        call_id=res_timeout.tool_call.call_id,
    )
    verifs = runtime.verify_claims([c_timeout])
    assert verifs.get("clm-timeout").verdict == ClaimVerdict.CONTRADICTED

    # Cancelled execution
    def cancel_tool(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        return ToolExecutionOutcome.cancelled()

    res_cancel = runtime.execute(Action(tool_name="abort_tool"), cancel_tool)
    assert res_cancel.tool_result.status == ToolResultStatus.CANCELLED
    assert res_cancel.is_success is False

    c_cancel = Claim(
        claim_id="clm-cancel",
        claim_type=ClaimType.TOOL_SUCCEEDED,
        description="abort tool should have succeeded",
        trace_id=runtime.trace_id,
        call_id=res_cancel.tool_call.call_id,
    )
    verifs2 = runtime.verify_claims([c_cancel])
    assert verifs2.get("clm-cancel").verdict == ClaimVerdict.CONTRADICTED


def test_runtime_file_exists_claim_verification() -> None:
    runtime = AgentContractRuntime()

    def file_creator(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        return ToolExecutionOutcome.success(
            output={"created_paths": ["/workspace/build.bin"]},
            changed_paths=["/workspace/build.bin"],
        )

    res = runtime.execute(
        Action(tool_name="builder", action_kind=ActionKind.FILE_WRITE),
        file_creator,
    )
    assert res.is_success is True

    claim = Claim(
        claim_id="build-file-claim",
        claim_type=ClaimType.FILE_EXISTS,
        description="binary exists",
        trace_id=runtime.trace_id,
        target_path="/workspace/build.bin",
    )
    verifs = runtime.verify_claims([claim])
    assert verifs.all_verified is True
    assert verifs.get("build-file-claim").verdict == ClaimVerdict.VERIFIED


def test_runtime_dependency_injection_and_batch_constraints() -> None:
    ledger = ConstraintLedger()
    c1 = _make_constraint("C-1", "Rule 1", strength=ConstraintStrength.SOFT)
    c2 = _make_constraint("C-2", "Rule 2", strength=ConstraintStrength.HARD)

    runtime = AgentContractRuntime(
        ledger=ledger,
        trace_id="custom_trace_999",
        session_id="custom_session_1",
    )
    added = runtime.add_constraints([c1, c2])
    assert len(added) == 2
    assert runtime.trace_id == "custom_trace_999"
    assert runtime.session_id == "custom_session_1"
    assert len(runtime.ledger) == 2

