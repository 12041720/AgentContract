"""Tests for benchmark metric formulas and edge-case behavior."""

import pytest

from agentcontract.benchmark.models import (
    BenchmarkMetrics,
    BenchmarkVariant,
    ScenarioResult,
)


def test_metric_formulas_on_hand_computed_toy_inputs() -> None:
    # 2 scenario results:
    # Scenario 1:
    #   violating_attempted: 2, violating_executed: 1
    #   positive_claims: 3, unsupported_accepted: 1
    #   non_violating_attempted: 4, non_violating_blocked: 1
    #   actual_task_success: True
    #   tool_calls: 3, extra_tool_calls: 1, trace_events: 6, duration: 10.0 ms
    # Scenario 2:
    #   violating_attempted: 2, violating_executed: 1
    #   positive_claims: 1, unsupported_accepted: 1
    #   non_violating_attempted: 2, non_violating_blocked: 0
    #   actual_task_success: False
    #   tool_calls: 2, extra_tool_calls: 1, trace_events: 4, duration: 20.0 ms
    r1 = ScenarioResult(
        scenario_id="s1",
        variant=BenchmarkVariant.SPECGUARD,
        variant_claimed_success=True,
        actual_task_success=True,
        violating_actions_attempted=2,
        violating_actions_executed=1,
        non_violating_actions_attempted=4,
        non_violating_actions_blocked=1,
        positive_claims_asserted=3,
        unsupported_claims_accepted=1,
        total_tool_calls=3,
        extra_tool_calls=1,
        trace_event_count=6,
        duration_ms=10.0,
    )
    r2 = ScenarioResult(
        scenario_id="s2",
        variant=BenchmarkVariant.SPECGUARD,
        variant_claimed_success=False,
        actual_task_success=False,
        violating_actions_attempted=2,
        violating_actions_executed=1,
        non_violating_actions_attempted=2,
        non_violating_actions_blocked=0,
        positive_claims_asserted=1,
        unsupported_claims_accepted=1,
        total_tool_calls=2,
        extra_tool_calls=1,
        trace_event_count=4,
        duration_ms=20.0,
    )

    metrics = BenchmarkMetrics.compute(
        variant=BenchmarkVariant.SPECGUARD,
        results=[r1, r2],
        baseline_avg_latency_ms=12.0,
    )

    # Aggregates:
    # violating_attempted = 4, violating_executed = 2 -> CVR = 2/4 = 0.5
    assert metrics.violating_actions_attempted == 4
    assert metrics.violating_actions_executed == 2
    assert metrics.constraint_violation_rate == 0.5

    # positive_claims = 4, unsupported_accepted = 2 -> UCR = 2/4 = 0.5
    assert metrics.positive_claims_asserted == 4
    assert metrics.unsupported_claims_accepted == 2
    assert metrics.unsupported_completion_rate == 0.5

    # non_violating_attempted = 6, non_violating_blocked = 1 -> FBR = 1/6 = 0.16666...
    assert metrics.non_violating_actions_attempted == 6
    assert metrics.non_violating_actions_blocked == 1
    assert metrics.false_blocking_rate == pytest.approx(1 / 6)

    # tasks = 2, successful = 1 -> TSR = 1/2 = 0.5
    assert metrics.total_tasks == 2
    assert metrics.successful_tasks == 1
    assert metrics.task_success_rate == 0.5

    # tool calls: total 5, avg 2.5, extra 2
    assert metrics.total_tool_calls == 5
    assert metrics.avg_tool_calls_per_run == 2.5
    assert metrics.total_extra_tool_calls == 2

    # trace events: total 10, avg 5.0
    assert metrics.total_trace_events == 10
    assert metrics.avg_trace_events_per_run == 5.0

    # duration: total 30.0, avg 15.0
    assert metrics.total_duration_ms == 30.0
    assert metrics.avg_latency_ms == 15.0

    # latency overhead: 15.0 - 12.0 = 3.0 ms
    assert metrics.latency_overhead_ms == 3.0

    # Negative latency delta (faster than baseline) must NOT be clipped to zero
    faster_metrics = BenchmarkMetrics.compute(
        variant=BenchmarkVariant.SPECGUARD,
        results=[r1, r2],
        baseline_avg_latency_ms=20.0,
    )
    assert faster_metrics.latency_overhead_ms == -5.0


def test_denominator_zero_behavior_is_explicit_and_safe() -> None:
    # Result with 0 for all denominators
    r = ScenarioResult(
        scenario_id="empty_s",
        variant=BenchmarkVariant.BASELINE,
        variant_claimed_success=True,
        actual_task_success=True,
        violating_actions_attempted=0,
        violating_actions_executed=0,
        non_violating_actions_attempted=0,
        non_violating_actions_blocked=0,
        positive_claims_asserted=0,
        unsupported_claims_accepted=0,
        total_tool_calls=0,
        extra_tool_calls=0,
        trace_event_count=0,
        duration_ms=0.0,
    )

    metrics = BenchmarkMetrics.compute(
        variant=BenchmarkVariant.BASELINE,
        results=[r],
    )

    # All ratios with zero denominators must evaluate to None
    assert metrics.constraint_violation_rate is None
    assert metrics.unsupported_completion_rate is None
    assert metrics.false_blocking_rate is None
    # total_tasks is 1 here, so TSR is 1.0
    assert metrics.task_success_rate == 1.0


def test_empty_results_list_denominator_zero() -> None:
    metrics = BenchmarkMetrics.compute(
        variant=BenchmarkVariant.BASELINE,
        results=[],
    )
    assert metrics.total_runs == 0
    assert metrics.constraint_violation_rate is None
    assert metrics.unsupported_completion_rate is None
    assert metrics.false_blocking_rate is None
    assert metrics.task_success_rate is None
    assert metrics.avg_tool_calls_per_run == 0.0
    assert metrics.avg_trace_events_per_run == 0.0
    assert metrics.avg_latency_ms == 0.0
    assert metrics.latency_overhead_ms is None
