"""Benchmark evaluation harness and reliability metrics for AgentContract."""

from agentcontract.benchmark.models import (
    BenchmarkMetrics,
    BenchmarkReport,
    BenchmarkScenario,
    BenchmarkVariant,
    ScenarioExecutionRecord,
    ScenarioResult,
    ScriptedAction,
)
from agentcontract.benchmark.runner import BenchmarkRunner
from agentcontract.benchmark.scenarios import (
    ALL_STANDARD_SCENARIOS,
    SCENARIO_AMBIGUOUS_REPEATED_CALLS,
    SCENARIO_CLEAN_SUCCESSFUL_TASK,
    SCENARIO_FAILED_TOOL_FALSE_CLAIM,
    SCENARIO_FILE_EXISTS_NO_EVIDENCE,
    SCENARIO_FORBIDDEN_WRITE,
    SCENARIO_POST_ACTION_VIOLATION,
    SCENARIO_REQUIRE_COMPLIANCE,
    SCENARIO_SOFT_WARNING,
    SCENARIO_STALE_FILE_STATE,
    SCENARIO_TESTS_PASSED_NO_EVIDENCE,
    SCENARIO_TIMEOUT_EXECUTION,
    SCENARIO_UNRELATED_CONSTRAINT,
    get_standard_scenarios,
)

__all__ = [
    "ALL_STANDARD_SCENARIOS",
    "BenchmarkMetrics",
    "BenchmarkReport",
    "BenchmarkRunner",
    "BenchmarkScenario",
    "BenchmarkVariant",
    "SCENARIO_AMBIGUOUS_REPEATED_CALLS",
    "SCENARIO_CLEAN_SUCCESSFUL_TASK",
    "SCENARIO_FAILED_TOOL_FALSE_CLAIM",
    "SCENARIO_FILE_EXISTS_NO_EVIDENCE",
    "SCENARIO_FORBIDDEN_WRITE",
    "SCENARIO_POST_ACTION_VIOLATION",
    "SCENARIO_REQUIRE_COMPLIANCE",
    "SCENARIO_SOFT_WARNING",
    "SCENARIO_STALE_FILE_STATE",
    "SCENARIO_TESTS_PASSED_NO_EVIDENCE",
    "SCENARIO_TIMEOUT_EXECUTION",
    "SCENARIO_UNRELATED_CONSTRAINT",
    "ScenarioExecutionRecord",
    "ScenarioResult",
    "ScriptedAction",
    "get_standard_scenarios",
]
