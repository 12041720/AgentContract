"""Tests for BenchmarkRunner execution, variant isolation, and reliability scenarios."""

import pytest

from agentcontract.benchmark.models import BenchmarkVariant
from agentcontract.benchmark.runner import BenchmarkRunner
from agentcontract.benchmark.scenarios import (
    SCENARIO_AMBIGUOUS_REPEATED_CALLS,
    SCENARIO_CLEAN_SUCCESSFUL_TASK,
    SCENARIO_FAILED_TOOL_FALSE_CLAIM,
    SCENARIO_FORBIDDEN_WRITE,
    SCENARIO_POST_ACTION_VIOLATION,
    SCENARIO_STALE_FILE_STATE,
    SCENARIO_TESTS_PASSED_NO_EVIDENCE,
    SCENARIO_TIMEOUT_EXECUTION,
    SCENARIO_UNRELATED_CONSTRAINT,
    get_standard_scenarios,
)
from agentcontract.evidence.models import ClaimVerdict


def test_baseline_allows_prohibited_action_that_specguard_prevents() -> None:
    runner = BenchmarkRunner()

    # 1. Baseline executes the forbidden write
    res_base = runner.run_scenario(SCENARIO_FORBIDDEN_WRITE, BenchmarkVariant.BASELINE)
    assert res_base.violating_actions_attempted == 1
    assert res_base.violating_actions_executed == 1
    assert res_base.records[0].executed is True
    assert res_base.records[0].was_violation_executed is True
    assert res_base.actual_task_success is False

    # 2. SpecGuard blocks the forbidden write before execution
    res_sg = runner.run_scenario(SCENARIO_FORBIDDEN_WRITE, BenchmarkVariant.SPECGUARD)
    assert res_sg.violating_actions_attempted == 1
    assert res_sg.violating_actions_executed == 0
    assert res_sg.records[0].executed is False
    assert res_sg.records[0].was_violation_prevented is True
    assert res_sg.actual_task_success is False

    # 3. Full AgentContract also blocks the forbidden write
    res_full = runner.run_scenario(SCENARIO_FORBIDDEN_WRITE, BenchmarkVariant.FULL_AGENTCONTRACT)
    assert res_full.violating_actions_attempted == 1
    assert res_full.violating_actions_executed == 0
    assert res_full.records[0].executed is False
    assert res_full.records[0].was_violation_prevented is True


def test_evidencegate_catches_unsupported_claim_baseline_accepts() -> None:
    runner = BenchmarkRunner()

    # Failed tool false claim
    # Baseline accepts the fake claim
    res_base = runner.run_scenario(SCENARIO_FAILED_TOOL_FALSE_CLAIM, BenchmarkVariant.BASELINE)
    assert res_base.positive_claims_asserted == 1
    assert res_base.unsupported_claims_accepted == 1
    assert len(res_base.accepted_claims) == 1
    assert res_base.actual_task_success is False

    # EvidenceGate evaluates evidence and CONTRADICTS the claim
    res_eg = runner.run_scenario(SCENARIO_FAILED_TOOL_FALSE_CLAIM, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg.positive_claims_asserted == 1
    assert res_eg.unsupported_claims_accepted == 0
    assert len(res_eg.accepted_claims) == 0
    assert res_eg.claim_evaluations[0].verdict == ClaimVerdict.CONTRADICTED

    # Tests passed without evidence
    res_base_test = runner.run_scenario(SCENARIO_TESTS_PASSED_NO_EVIDENCE, BenchmarkVariant.BASELINE)
    assert res_base_test.unsupported_claims_accepted == 1

    res_eg_test = runner.run_scenario(SCENARIO_TESTS_PASSED_NO_EVIDENCE, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg_test.unsupported_claims_accepted == 0
    assert res_eg_test.claim_evaluations[0].verdict == ClaimVerdict.UNVERIFIED


def test_unrelated_constraint_does_not_inflate_false_blocking() -> None:
    runner = BenchmarkRunner()

    for variant in (
        BenchmarkVariant.BASELINE,
        BenchmarkVariant.SPECGUARD,
        BenchmarkVariant.EVIDENCEGATE,
        BenchmarkVariant.FULL_AGENTCONTRACT,
    ):
        res = runner.run_scenario(SCENARIO_UNRELATED_CONSTRAINT, variant)
        assert res.non_violating_actions_attempted == 1
        assert res.non_violating_actions_blocked == 0
        assert res.records[0].was_false_blocked is False
        assert res.actual_task_success is True


def test_post_action_violation_detected_and_counted_correctly() -> None:
    runner = BenchmarkRunner()

    # Baseline executes without awareness
    res_base = runner.run_scenario(SCENARIO_POST_ACTION_VIOLATION, BenchmarkVariant.BASELINE)
    assert res_base.violating_actions_executed == 1
    assert res_base.records[0].post_decision is None

    # SpecGuard allows pre-action, but post-action guard blocks
    res_sg = runner.run_scenario(SCENARIO_POST_ACTION_VIOLATION, BenchmarkVariant.SPECGUARD)
    assert res_sg.records[0].executed is True
    assert res_sg.records[0].pre_decision.is_allowed is True
    assert res_sg.records[0].post_decision.is_blocked is True
    assert res_sg.violating_actions_executed == 1

    # Full AgentContract detects post-action violation via runtime
    res_full = runner.run_scenario(SCENARIO_POST_ACTION_VIOLATION, BenchmarkVariant.FULL_AGENTCONTRACT)
    assert res_full.records[0].executed is True
    assert res_full.records[0].pre_decision.is_allowed is True
    assert res_full.records[0].post_decision.is_blocked is True


def test_stale_file_state_evidence_contradiction() -> None:
    runner = BenchmarkRunner()

    # Baseline accepts the claim that lock file exists
    res_base = runner.run_scenario(SCENARIO_STALE_FILE_STATE, BenchmarkVariant.BASELINE)
    assert res_base.unsupported_claims_accepted == 1

    # EvidenceGate checks latest trace state (deleted) and CONTRADICTS
    res_eg = runner.run_scenario(SCENARIO_STALE_FILE_STATE, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg.unsupported_claims_accepted == 0
    assert len(res_eg.accepted_claims) == 0
    assert res_eg.claim_evaluations[0].verdict == ClaimVerdict.CONTRADICTED


def test_ambiguous_repeated_calls_unverified() -> None:
    runner = BenchmarkRunner()

    res_eg = runner.run_scenario(SCENARIO_AMBIGUOUS_REPEATED_CALLS, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg.unsupported_claims_accepted == 0
    assert len(res_eg.accepted_claims) == 0
    assert res_eg.claim_evaluations[0].verdict == ClaimVerdict.UNVERIFIED


def test_timeout_execution_contradiction() -> None:
    runner = BenchmarkRunner()

    res_eg = runner.run_scenario(SCENARIO_TIMEOUT_EXECUTION, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg.unsupported_claims_accepted == 0
    assert len(res_eg.accepted_claims) == 0
    assert res_eg.claim_evaluations[0].verdict == ClaimVerdict.CONTRADICTED


def test_clean_successful_task_succeeds_in_all_variants() -> None:
    runner = BenchmarkRunner()

    res_base = runner.run_scenario(SCENARIO_CLEAN_SUCCESSFUL_TASK, BenchmarkVariant.BASELINE)
    assert res_base.actual_task_success is True

    res_sg = runner.run_scenario(SCENARIO_CLEAN_SUCCESSFUL_TASK, BenchmarkVariant.SPECGUARD)
    assert res_sg.actual_task_success is True

    res_eg = runner.run_scenario(SCENARIO_CLEAN_SUCCESSFUL_TASK, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg.actual_task_success is True

    res_full = runner.run_scenario(SCENARIO_CLEAN_SUCCESSFUL_TASK, BenchmarkVariant.FULL_AGENTCONTRACT)
    assert res_full.actual_task_success is True
    assert len(res_full.accepted_claims) == 2
    assert all(ev.verdict == ClaimVerdict.VERIFIED for ev in res_full.claim_evaluations)


def test_variant_isolation() -> None:
    runner = BenchmarkRunner()

    # 1. BASELINE: zero trace events, no guard decisions
    res_base = runner.run_scenario(SCENARIO_FORBIDDEN_WRITE, BenchmarkVariant.BASELINE)
    assert res_base.trace_event_count == 0
    assert res_base.records[0].pre_decision is None
    assert len(res_base.claim_evaluations) == 0

    # 2. SPECGUARD: guard active, zero trace events, no claim evaluations
    res_sg = runner.run_scenario(SCENARIO_FORBIDDEN_WRITE, BenchmarkVariant.SPECGUARD)
    assert res_sg.trace_event_count == 0
    assert res_sg.records[0].pre_decision is not None
    assert len(res_sg.claim_evaluations) == 0

    # 3. EVIDENCEGATE: guard inactive (pre_decision is None), trace events recorded, claim evaluated
    res_eg = runner.run_scenario(SCENARIO_FAILED_TOOL_FALSE_CLAIM, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg.records[0].pre_decision is None
    assert res_eg.trace_event_count > 0
    assert len(res_eg.claim_evaluations) > 0

    # 4. FULL: both guard and gate active
    res_full = runner.run_scenario(SCENARIO_CLEAN_SUCCESSFUL_TASK, BenchmarkVariant.FULL_AGENTCONTRACT)
    assert res_full.records[0].pre_decision is not None
    assert res_full.trace_event_count > 0
    assert len(res_full.claim_evaluations) > 0


def test_repeated_deterministic_runs_are_identical() -> None:
    runner = BenchmarkRunner()
    scenarios = get_standard_scenarios()

    report = runner.run(scenarios=scenarios, repetitions=2)

    assert report.repetitions == 2
    assert report.scenario_count == len(scenarios)

    # Group results by (variant, scenario_id) across repetitions
    grouped: dict[tuple[BenchmarkVariant, str], list] = {}
    for res in report.scenario_results:
        key = (res.variant, res.scenario_id)
        grouped.setdefault(key, []).append(res)

    for (var, sid), res_list in grouped.items():
        assert len(res_list) == 2, f"Expected 2 repetitions for {var}, {sid}"
        r1, r2 = res_list[0], res_list[1]

        # Reliability counters and task truth must be strictly identical
        assert r1.actual_task_success == r2.actual_task_success
        assert r1.variant_claimed_success == r2.variant_claimed_success
        assert r1.violating_actions_attempted == r2.violating_actions_attempted
        assert r1.violating_actions_executed == r2.violating_actions_executed
        assert r1.non_violating_actions_attempted == r2.non_violating_actions_attempted
        assert r1.non_violating_actions_blocked == r2.non_violating_actions_blocked
        assert r1.positive_claims_asserted == r2.positive_claims_asserted
        assert r1.unsupported_claims_accepted == r2.unsupported_claims_accepted
        assert r1.total_tool_calls == r2.total_tool_calls
        assert r1.extra_tool_calls == r2.extra_tool_calls
        assert r1.trace_event_count == r2.trace_event_count

        # Action execution states and decisions must match
        assert len(r1.records) == len(r2.records)
        for rec1, rec2 in zip(r1.records, r2.records):
            assert rec1.executed == rec2.executed
            assert rec1.was_violation_executed == rec2.was_violation_executed
            assert rec1.was_violation_prevented == rec2.was_violation_prevented
            assert rec1.was_false_blocked == rec2.was_false_blocked
            if rec1.pre_decision and rec2.pre_decision:
                assert rec1.pre_decision.decision == rec2.pre_decision.decision
            if rec1.post_decision and rec2.post_decision:
                assert rec1.post_decision.decision == rec2.post_decision.decision

        # Claim evaluations must match
        assert len(r1.claim_evaluations) == len(r2.claim_evaluations)
        for ev1, ev2 in zip(r1.claim_evaluations, r2.claim_evaluations):
            assert ev1.claim.claim_id == ev2.claim.claim_id
            assert ev1.verdict == ev2.verdict


def test_full_benchmark_run_and_report() -> None:
    runner = BenchmarkRunner()
    scenarios = get_standard_scenarios()
    report = runner.run(scenarios=scenarios, repetitions=1)

    assert len(report.metrics) == 4
    for var in BenchmarkVariant:
        assert var in report.metrics
        m = report.metrics[var]
        assert m.total_scenarios == len(scenarios)
        assert m.total_runs == len(scenarios)
        # Verify valid bounded numeric metrics without hardcoding marketing winner assertions
        assert m.constraint_violation_rate is not None
        assert 0.0 <= m.constraint_violation_rate <= 1.0
        assert m.unsupported_completion_rate is not None
        assert 0.0 <= m.unsupported_completion_rate <= 1.0
        assert m.false_blocking_rate is not None
        assert 0.0 <= m.false_blocking_rate <= 1.0
        assert m.task_success_rate is not None
        assert 0.0 <= m.task_success_rate <= 1.0
        assert m.total_tool_calls >= 0
        assert m.total_extra_tool_calls >= 0

    base_m = report.metrics[BenchmarkVariant.BASELINE]
    full_m = report.metrics[BenchmarkVariant.FULL_AGENTCONTRACT]

    # Structural mechanics: FULL records trace events; BASELINE does not
    assert full_m.total_trace_events > 0
    assert base_m.total_trace_events == 0
    assert full_m.avg_latency_ms >= 0.0


def test_tsr_decoupled_from_unsupported_claims() -> None:
    from agentcontract.benchmark.scenarios import SCENARIO_SUCCESS_WITH_UNSUPPORTED_CLAIM

    runner = BenchmarkRunner()

    # Baseline: actual task succeeds, but accepts unsupported claim
    res_base = runner.run_scenario(SCENARIO_SUCCESS_WITH_UNSUPPORTED_CLAIM, BenchmarkVariant.BASELINE)
    assert res_base.actual_task_success is True
    assert res_base.variant_claimed_success is True
    assert res_base.positive_claims_asserted == 2
    assert res_base.unsupported_claims_accepted == 1

    # SpecGuard: actual task succeeds, but accepts unsupported claim (gate disabled)
    res_sg = runner.run_scenario(SCENARIO_SUCCESS_WITH_UNSUPPORTED_CLAIM, BenchmarkVariant.SPECGUARD)
    assert res_sg.actual_task_success is True
    assert res_sg.variant_claimed_success is True
    assert res_sg.unsupported_claims_accepted == 1

    # EvidenceGate: actual task succeeds, rejects unsupported claim
    res_eg = runner.run_scenario(SCENARIO_SUCCESS_WITH_UNSUPPORTED_CLAIM, BenchmarkVariant.EVIDENCEGATE)
    assert res_eg.actual_task_success is True
    assert res_eg.variant_claimed_success is False
    assert res_eg.unsupported_claims_accepted == 0

    # Full AgentContract: actual task succeeds, rejects unsupported claim
    res_full = runner.run_scenario(SCENARIO_SUCCESS_WITH_UNSUPPORTED_CLAIM, BenchmarkVariant.FULL_AGENTCONTRACT)
    assert res_full.actual_task_success is True
    assert res_full.variant_claimed_success is False
    assert res_full.positive_claims_asserted == 2
    assert res_full.unsupported_claims_accepted == 0


def test_extra_tool_calls_measured_against_ground_truth() -> None:
    runner = BenchmarkRunner()

    # Clean task: 2 executed, 2 expected -> extra = 0
    res_clean = runner.run_scenario(SCENARIO_CLEAN_SUCCESSFUL_TASK, BenchmarkVariant.FULL_AGENTCONTRACT)
    assert res_clean.total_tool_calls == 2
    assert res_clean.extra_tool_calls == 0

    # Forbidden write: expected 0 clean calls. Baseline executes 1 -> extra = 1
    res_base_f = runner.run_scenario(SCENARIO_FORBIDDEN_WRITE, BenchmarkVariant.BASELINE)
    assert res_base_f.total_tool_calls == 1
    assert res_base_f.extra_tool_calls == 1

    # SpecGuard blocks: 0 executed, 0 expected -> extra = 0
    res_sg_f = runner.run_scenario(SCENARIO_FORBIDDEN_WRITE, BenchmarkVariant.SPECGUARD)
    assert res_sg_f.total_tool_calls == 0
    assert res_sg_f.extra_tool_calls == 0


def test_fbr_counts_only_pre_action_false_blocking() -> None:
    from agentcontract.constraints.models import (
        Constraint,
        ConstraintProvenance,
        ConstraintScope,
        ConstraintSource,
        ConstraintStrength,
        RuleEffect,
    )
    from agentcontract.benchmark.models import BenchmarkMetrics, BenchmarkScenario, ScriptedAction
    from agentcontract.guard.models import Action, ActionKind

    # Scenario with false pre-action block: benign read blocked by misconfigured HARD DENY rule
    false_pre_block_scen = BenchmarkScenario(
        scenario_id="scen_false_pre_block",
        title="False pre-block",
        description="Benign read blocked before execution",
        initial_constraints=(
            Constraint(
                id="c_erroneous_block",
                name="erroneous_block",
                description="Erroneous block",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.POLICY, source_text="rule", author="admin"),
                scope=ConstraintScope(tools=("reader",)),
            ),
        ),
        scripted_actions=(
            ScriptedAction(
                action=Action(tool_name="reader", action_kind=ActionKind.FILE_READ, target_path="data.txt"),
                is_violation=False,
            ),
        ),
        expected_task_success=True,
        expected_tool_calls=1,
    )

    runner = BenchmarkRunner()
    res_sg = runner.run_scenario(false_pre_block_scen, BenchmarkVariant.SPECGUARD)
    assert res_sg.records[0].executed is False
    assert res_sg.records[0].was_false_blocked is True
    assert res_sg.non_violating_actions_blocked == 1
    m = BenchmarkMetrics.compute(variant=BenchmarkVariant.SPECGUARD, results=[res_sg])
    assert m.false_blocking_rate == 1.0

    # Post-action block on violation does NOT count towards FBR
    res_post_viol = runner.run_scenario(SCENARIO_POST_ACTION_VIOLATION, BenchmarkVariant.SPECGUARD)
    assert res_post_viol.records[0].executed is True
    assert res_post_viol.records[0].was_false_blocked is False
    assert res_post_viol.non_violating_actions_blocked == 0


def test_runner_run_input_validation() -> None:
    runner = BenchmarkRunner()

    # repetitions < 1
    with pytest.raises(ValueError, match="repetitions must be >= 1"):
        runner.run(repetitions=0)

    # duplicate scenario IDs
    scen = SCENARIO_CLEAN_SUCCESSFUL_TASK
    with pytest.raises(ValueError, match="Duplicate scenario_id"):
        runner.run(scenarios=[scen, scen])

    # duplicate variants
    with pytest.raises(ValueError, match="Duplicate variants"):
        runner.run(variants=[BenchmarkVariant.BASELINE, BenchmarkVariant.BASELINE])
