"""Domain models for benchmark scenarios, execution records, metrics, and reports."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict, _freeze_value
from agentcontract.constraints.models import Constraint
from agentcontract.evidence.models import Claim, ClaimEvaluation, ClaimVerdict
from agentcontract.guard.models import Action, GuardDecision
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.trace.models import ToolCall, ToolResult


class BenchmarkVariant(StrEnum):
    """Execution mode under evaluation in the reliability benchmark."""

    BASELINE = "BASELINE"
    SPECGUARD = "SPECGUARD"
    EVIDENCEGATE = "EVIDENCEGATE"
    FULL_AGENTCONTRACT = "FULL_AGENTCONTRACT"


class ScriptedAction(BaseModel):
    """Deterministic action step executed by an agent in a benchmark scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Action = Field(..., description="Proposed agent action.")
    is_violation: bool = Field(
        default=False,
        description="Ground truth: True if this action actually violates a constraint in this scenario.",
    )
    outcome: ToolExecutionOutcome | None = Field(
        default=None,
        description="Mock outcome produced if the tool is executed. Defaults to generic success if None.",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of this scripted action step.",
    )

    def get_outcome(self) -> ToolExecutionOutcome:
        """Resolve the tool execution outcome for this action."""
        if self.outcome is not None:
            return self.outcome
        return ToolExecutionOutcome.success(
            output=f"Executed {self.action.tool_name or 'tool'}",
            exit_code=0,
        )


class BenchmarkScenario(BaseModel):
    """Specification of a deterministic benchmark scenario with ground truth expectations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(..., description="Unique machine-readable scenario identifier.")
    title: str = Field(..., description="Short descriptive title.")
    description: str = Field(..., description="Detailed description of the scenario behavior and context.")
    initial_constraints: tuple[Constraint, ...] = Field(
        default_factory=tuple,
        description="Active constraints configured before task execution.",
    )
    scripted_actions: tuple[ScriptedAction, ...] = Field(
        default_factory=tuple,
        description="Chronological sequence of actions attempted by the scripted agent.",
    )
    completion_claims: tuple[Claim, ...] = Field(
        default_factory=tuple,
        description="Completion claims asserted by the agent upon task finish.",
    )
    ground_truth_supported_claims: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Claim IDs of claims that are actually supported and truthful in reality.",
    )
    expected_task_success: bool = Field(
        default=False,
        description="Ground truth: True if the legitimate task objective is expected to succeed cleanly.",
    )
    tags: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Categorical tags for filtering and analysis.",
    )

    @field_validator("scenario_id", "title")
    @classmethod
    def _validate_non_empty_str(cls, val: str) -> str:
        s = val.strip()
        if not s:
            raise ValueError("scenario_id and title cannot be blank.")
        return s

    @property
    def total_actions(self) -> int:
        """Total number of actions attempted in this scenario."""
        return len(self.scripted_actions)

    @property
    def total_violating_actions(self) -> int:
        """Total number of ground-truth violating actions in this scenario."""
        return sum(1 for a in self.scripted_actions if a.is_violation)

    @property
    def total_non_violating_actions(self) -> int:
        """Total number of ground-truth non-violating actions in this scenario."""
        return sum(1 for a in self.scripted_actions if not a.is_violation)


class ScenarioExecutionRecord(BaseModel):
    """Trace and decision record for a single action step within a scenario execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_index: int = Field(..., description="0-indexed step sequence within scenario.")
    action: Action = Field(..., description="Action attempted.")
    is_ground_truth_violation: bool = Field(..., description="Whether action was ground truth violation.")
    pre_decision: GuardDecision | None = Field(default=None, description="Pre-action SpecGuard decision.")
    executed: bool = Field(default=False, description="Whether tool execution took place.")
    tool_call: ToolCall | None = Field(default=None, description="Recorded ToolCall model if executed.")
    tool_result: ToolResult | None = Field(default=None, description="Recorded ToolResult model if executed.")
    post_decision: GuardDecision | None = Field(default=None, description="Post-action SpecGuard decision.")
    was_violation_executed: bool = Field(
        default=False,
        description="True if an actual violating action executed.",
    )
    was_violation_prevented: bool = Field(
        default=False,
        description="True if an actual violating action was prevented by pre-action blocking.",
    )
    was_false_blocked: bool = Field(
        default=False,
        description="True if an action was NOT a violation but was blocked.",
    )


class ScenarioResult(BaseModel):
    """Outcome and detailed provenance of executing a scenario under a specific variant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(..., description="Identifier of the scenario.")
    variant: BenchmarkVariant = Field(..., description="Variant under which the scenario was run.")
    iteration: int = Field(default=1, description="Repetition index (1-based).")
    records: tuple[ScenarioExecutionRecord, ...] = Field(
        default_factory=tuple,
        description="Chronological action execution records.",
    )
    claim_evaluations: tuple[ClaimEvaluation, ...] = Field(
        default_factory=tuple,
        description="Evaluations produced by EvidenceGate (empty if EvidenceGate disabled).",
    )
    accepted_claims: tuple[Claim, ...] = Field(
        default_factory=tuple,
        description="Claims accepted as successful by the variant.",
    )
    variant_claimed_success: bool = Field(
        ...,
        description="Whether the variant concluded that the task succeeded.",
    )
    actual_task_success: bool = Field(
        ...,
        description="Whether the task actually succeeded in reality (ground truth respected, no violations executed).",
    )
    violating_actions_attempted: int = Field(default=0)
    violating_actions_executed: int = Field(default=0)
    non_violating_actions_attempted: int = Field(default=0)
    non_violating_actions_blocked: int = Field(default=0)
    positive_claims_asserted: int = Field(default=0)
    unsupported_claims_accepted: int = Field(default=0)
    total_tool_calls: int = Field(default=0)
    extra_tool_calls: int = Field(default=0)
    trace_event_count: int = Field(default=0)
    duration_ms: float = Field(default=0.0)


class BenchmarkMetrics(BaseModel):
    """Reliability and overhead summary metrics aggregated for a benchmark variant.

    Exact Metric Definitions:
    - Constraint Violation Rate (CVR):
      `violating_actions_executed / violating_actions_attempted`
      Excluded/None if violating_actions_attempted == 0.
    - Unsupported Completion Rate (UCR):
      `unsupported_claims_accepted / positive_claims_asserted`
      Excluded/None if positive_claims_asserted == 0.
    - False Blocking Rate (FBR):
      `non_violating_actions_blocked / non_violating_actions_attempted`
      Excluded/None if non_violating_actions_attempted == 0.
    - Task Success Rate (TSR):
      `successful_tasks / total_tasks`
      Excluded/None if total_tasks == 0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    variant: BenchmarkVariant = Field(..., description="Evaluated variant.")
    total_scenarios: int = Field(default=0, description="Distinct scenarios evaluated.")
    total_runs: int = Field(default=0, description="Total scenario runs across all repetitions.")

    # CVR
    violating_actions_attempted: int = Field(default=0)
    violating_actions_executed: int = Field(default=0)
    constraint_violation_rate: float | None = Field(default=None)

    # UCR
    positive_claims_asserted: int = Field(default=0)
    unsupported_claims_accepted: int = Field(default=0)
    unsupported_completion_rate: float | None = Field(default=None)

    # FBR
    non_violating_actions_attempted: int = Field(default=0)
    non_violating_actions_blocked: int = Field(default=0)
    false_blocking_rate: float | None = Field(default=None)

    # TSR
    total_tasks: int = Field(default=0)
    successful_tasks: int = Field(default=0)
    task_success_rate: float | None = Field(default=None)

    # Tool calls & overhead
    total_tool_calls: int = Field(default=0)
    avg_tool_calls_per_run: float = Field(default=0.0)
    total_extra_tool_calls: int = Field(default=0)
    total_trace_events: int = Field(default=0)
    avg_trace_events_per_run: float = Field(default=0.0)
    total_duration_ms: float = Field(default=0.0)
    avg_latency_ms: float = Field(default=0.0)
    latency_overhead_ms: float | None = Field(
        default=None,
        description="Average latency difference compared to BASELINE variant.",
    )

    @classmethod
    def compute(
        cls,
        variant: BenchmarkVariant,
        results: Sequence[ScenarioResult],
        baseline_avg_latency_ms: float | None = None,
    ) -> Self:
        """Compute aggregated metrics strictly from scenario run results."""
        total_runs = len(results)
        unique_scenarios = len({r.scenario_id for r in results})

        v_attempted = sum(r.violating_actions_attempted for r in results)
        v_executed = sum(r.violating_actions_executed for r in results)
        cvr = (v_executed / v_attempted) if v_attempted > 0 else None

        pos_claims = sum(r.positive_claims_asserted for r in results)
        unsupp_accepted = sum(r.unsupported_claims_accepted for r in results)
        ucr = (unsupp_accepted / pos_claims) if pos_claims > 0 else None

        nv_attempted = sum(r.non_violating_actions_attempted for r in results)
        nv_blocked = sum(r.non_violating_actions_blocked for r in results)
        fbr = (nv_blocked / nv_attempted) if nv_attempted > 0 else None

        total_tasks = total_runs
        successful_tasks = sum(1 for r in results if r.actual_task_success)
        tsr = (successful_tasks / total_tasks) if total_tasks > 0 else None

        total_calls = sum(r.total_tool_calls for r in results)
        avg_calls = (total_calls / total_runs) if total_runs > 0 else 0.0

        total_extra = sum(r.extra_tool_calls for r in results)

        total_events = sum(r.trace_event_count for r in results)
        avg_events = (total_events / total_runs) if total_runs > 0 else 0.0

        total_duration = sum(r.duration_ms for r in results)
        avg_latency = (total_duration / total_runs) if total_runs > 0 else 0.0

        overhead_ms: float | None = None
        if baseline_avg_latency_ms is not None:
            overhead_ms = max(0.0, avg_latency - baseline_avg_latency_ms)

        return cls(
            variant=variant,
            total_scenarios=unique_scenarios,
            total_runs=total_runs,
            violating_actions_attempted=v_attempted,
            violating_actions_executed=v_executed,
            constraint_violation_rate=cvr,
            positive_claims_asserted=pos_claims,
            unsupported_claims_accepted=unsupp_accepted,
            unsupported_completion_rate=ucr,
            non_violating_actions_attempted=nv_attempted,
            non_violating_actions_blocked=nv_blocked,
            false_blocking_rate=fbr,
            total_tasks=total_tasks,
            successful_tasks=successful_tasks,
            task_success_rate=tsr,
            total_tool_calls=total_calls,
            avg_tool_calls_per_run=round(avg_calls, 3),
            total_extra_tool_calls=total_extra,
            total_trace_events=total_events,
            avg_trace_events_per_run=round(avg_events, 3),
            total_duration_ms=round(total_duration, 3),
            avg_latency_ms=round(avg_latency, 3),
            latency_overhead_ms=round(overhead_ms, 3) if overhead_ms is not None else None,
        )


class BenchmarkReport(BaseModel):
    """Full serialized report of a completed benchmark evaluation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(..., description="Unique run identifier.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of report generation.",
    )
    repetitions: int = Field(default=1, description="Number of repetitions executed per scenario.")
    scenario_count: int = Field(..., description="Number of evaluated scenarios.")
    metrics: dict[BenchmarkVariant, BenchmarkMetrics] = Field(
        ...,
        description="Aggregated metrics indexed by benchmark variant.",
    )
    scenario_results: tuple[ScenarioResult, ...] = Field(
        default_factory=tuple,
        description="Detailed chronological scenario outcomes.",
    )
