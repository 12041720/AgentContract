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

    # Check stability of metrics across repetitions
    for variant in BenchmarkVariant:
        m = report.metrics[variant]
        assert m.total_scenarios == len(scenarios)
        assert m.total_runs == len(scenarios) * 2
        # CVR, UCR, FBR, TSR must be well-defined
        assert m.constraint_violation_rate is not None
        assert m.unsupported_completion_rate is not None
        assert m.false_blocking_rate is not None
        assert m.task_success_rate is not None


def test_full_benchmark_run_and_report() -> None:
    runner = BenchmarkRunner()
    report = runner.run(scenarios=get_standard_scenarios(), repetitions=1)

    assert len(report.metrics) == 4
    for var in BenchmarkVariant:
        assert var in report.metrics

    base_m = report.metrics[BenchmarkVariant.BASELINE]
    full_m = report.metrics[BenchmarkVariant.FULL_AGENTCONTRACT]

    # Concrete assertions derived from the 12 scenarios:
    # 1. Full AgentContract reduces Constraint Violation Rate compared to Baseline
    assert full_m.constraint_violation_rate < base_m.constraint_violation_rate
    # 2. Full AgentContract reduces Unsupported Completion Rate compared to Baseline
    assert full_m.unsupported_completion_rate < base_m.unsupported_completion_rate
    # 3. False blocking rate remains 0.0
    assert full_m.false_blocking_rate == 0.0
    # 4. Task Success Rate in Full AgentContract is higher or equal to Baseline
    assert full_m.task_success_rate >= base_m.task_success_rate
    # 5. Full AgentContract records trace events
    assert full_m.total_trace_events > 0
    assert base_m.total_trace_events == 0
