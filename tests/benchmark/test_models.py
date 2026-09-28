"""Tests for benchmark models, validation, and serialization."""

import json
import pytest

from agentcontract.benchmark.models import (
    BenchmarkMetrics,
    BenchmarkReport,
    BenchmarkScenario,
    BenchmarkVariant,
    ScenarioExecutionRecord,
    ScenarioResult,
    ScriptedAction,
)
from agentcontract.guard.models import Action, ActionKind
from agentcontract.runtime.models import ToolExecutionOutcome


def test_benchmark_variant_enum_values() -> None:
    assert BenchmarkVariant.BASELINE == "BASELINE"
    assert BenchmarkVariant.SPECGUARD == "SPECGUARD"
    assert BenchmarkVariant.EVIDENCEGATE == "EVIDENCEGATE"
    assert BenchmarkVariant.FULL_AGENTCONTRACT == "FULL_AGENTCONTRACT"


def test_scripted_action_model_and_get_outcome() -> None:
    action = Action(
        tool_name="bash",
        action_kind=ActionKind.COMMAND_EXEC,
        payload={"cmd": "ls -la"},
    )
    sa = ScriptedAction(
        action=action,
        is_violation=False,
    )
    outcome = sa.get_outcome()
    assert outcome.status.value == "SUCCESS"
    assert outcome.exit_code == 0

    # Custom outcome
    custom_outcome = ToolExecutionOutcome.failed("error message", exit_code=2)
    sa_custom = ScriptedAction(
        action=action,
        is_violation=True,
        outcome=custom_outcome,
        description="Failing action",
    )
    assert sa_custom.get_outcome().status.value != "SUCCESS"
    assert sa_custom.get_outcome().exit_code == 2

    # Extra fields forbidden
    with pytest.raises(Exception):
        ScriptedAction.model_validate(
            {
                "action": action.model_dump(),
                "unexpected_field": 123,
            }
        )


def test_benchmark_scenario_validation_and_properties() -> None:
    action = Action(tool_name="cat", target_path="test.txt")
    scen = BenchmarkScenario(
        scenario_id="scen_test",
        title="Test Scenario",
        description="A scenario for testing",
        scripted_actions=(
            ScriptedAction(action=action, is_violation=True),
            ScriptedAction(action=action, is_violation=False),
        ),
        expected_task_success=False,
        tags=("test", "demo"),
    )
    assert scen.total_actions == 2
    assert scen.total_violating_actions == 1
    assert scen.total_non_violating_actions == 1

    # Blank scenario_id rejected
    with pytest.raises(ValueError, match="cannot be blank"):
        BenchmarkScenario(
            scenario_id="   ",
            title="Title",
            description="Desc",
        )


def test_benchmark_report_serialization_and_round_trip() -> None:
    metrics = BenchmarkMetrics(
        variant=BenchmarkVariant.BASELINE,
        total_scenarios=1,
        total_runs=1,
        violating_actions_attempted=1,
        violating_actions_executed=1,
        constraint_violation_rate=1.0,
        positive_claims_asserted=1,
        unsupported_claims_accepted=1,
        unsupported_completion_rate=1.0,
        non_violating_actions_attempted=1,
        non_violating_actions_blocked=0,
        false_blocking_rate=0.0,
        total_tasks=1,
        successful_tasks=0,
        task_success_rate=0.0,
    )
    report = BenchmarkReport(
        run_id="run_12345",
        repetitions=1,
        scenario_count=1,
        metrics={BenchmarkVariant.BASELINE: metrics},
        scenario_results=(),
    )

    dumped = report.model_dump(mode="json")
    assert dumped["run_id"] == "run_12345"
    assert dumped["metrics"]["BASELINE"]["constraint_violation_rate"] == 1.0

    raw_json = report.model_dump_json()
    loaded = json.loads(raw_json)
    assert loaded["run_id"] == "run_12345"

    parsed = BenchmarkReport.model_validate_json(raw_json)
    assert parsed.run_id == report.run_id
    assert parsed.metrics[BenchmarkVariant.BASELINE].constraint_violation_rate == 1.0


def test_top_level_package_exports_benchmark() -> None:
    from agentcontract import (
        ALL_STANDARD_SCENARIOS as RootAllScenarios,
        BenchmarkMetrics as RootBenchmarkMetrics,
        BenchmarkReport as RootBenchmarkReport,
        BenchmarkRunner as RootBenchmarkRunner,
        BenchmarkScenario as RootBenchmarkScenario,
        BenchmarkVariant as RootBenchmarkVariant,
        ScenarioExecutionRecord as RootScenarioExecutionRecord,
        ScenarioResult as RootScenarioResult,
        ScriptedAction as RootScriptedAction,
        get_standard_scenarios as root_get_standard_scenarios,
    )

    assert RootBenchmarkRunner is not None
    assert RootBenchmarkVariant is not None
    assert RootBenchmarkScenario is not None
    assert RootBenchmarkMetrics is not None
    assert RootBenchmarkReport is not None
    assert len(RootAllScenarios) >= 12
    assert len(root_get_standard_scenarios()) >= 12
