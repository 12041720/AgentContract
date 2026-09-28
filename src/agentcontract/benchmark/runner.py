"""Benchmark runner executing scenarios across variants and calculating metrics."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import time
from typing import Any
import uuid

from agentcontract.benchmark.models import (
    BenchmarkMetrics,
    BenchmarkReport,
    BenchmarkScenario,
    BenchmarkVariant,
    ScenarioExecutionRecord,
    ScenarioResult,
    ScriptedAction,
)
from agentcontract.benchmark.scenarios import get_standard_scenarios
from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.evidence.gate import EvidenceGate
from agentcontract.evidence.models import Claim, ClaimEvaluation, ClaimVerdict
from agentcontract.guard.engine import SpecGuard
from agentcontract.guard.models import Action, ActionObservation, DecisionKind
from agentcontract.runtime.models import IdGenerator, ToolExecutionOutcome
from agentcontract.runtime.session import AgentContractRuntime
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
    _freeze_trace_value,
)
from agentcontract.trace.store import TraceStore


def _extract_arguments(action: Action) -> Mapping[str, Any]:
    """Safely extract dictionary arguments from action payload for ToolCall."""
    if isinstance(action.payload, Mapping):
        return action.payload
    return {}


class BenchmarkRunner:
    """Deterministic benchmark harness measuring reliability metrics and overhead."""

    def __init__(self, id_prefix: str = "bench_run_") -> None:
        self._id_prefix = id_prefix

    def run_scenario(
        self,
        scenario: BenchmarkScenario,
        variant: BenchmarkVariant,
        iteration: int = 1,
    ) -> ScenarioResult:
        """Execute a single scenario under a specific variant and record results."""
        t_start = time.perf_counter()

        if variant == BenchmarkVariant.BASELINE:
            result = self._run_baseline(scenario, iteration)
        elif variant == BenchmarkVariant.SPECGUARD:
            result = self._run_specguard(scenario, iteration)
        elif variant == BenchmarkVariant.EVIDENCEGATE:
            result = self._run_evidencegate(scenario, iteration)
        elif variant == BenchmarkVariant.FULL_AGENTCONTRACT:
            result = self._run_full(scenario, iteration)
        else:
            raise ValueError(f"Unknown benchmark variant: {variant}")

        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        # Return result with accurately measured elapsed milliseconds
        return result.model_copy(update={"duration_ms": round(elapsed_ms, 3)})

    def _run_baseline(self, scenario: BenchmarkScenario, iteration: int) -> ScenarioResult:
        """BASELINE: no SpecGuard, no EvidenceGate, blindly trust agent claims."""
        records: list[ScenarioExecutionRecord] = []
        violating_attempted = 0
        violating_executed = 0
        non_violating_attempted = 0
        total_calls = 0
        extra_calls = 0

        for idx, sa in enumerate(scenario.scripted_actions):
            if sa.is_violation:
                violating_attempted += 1
            else:
                non_violating_attempted += 1

            outcome = sa.get_outcome()
            executed = True
            total_calls += 1

            was_violation_exec = False
            if sa.is_violation:
                was_violation_exec = True
                violating_executed += 1
                extra_calls += 1

            records.append(
                ScenarioExecutionRecord(
                    step_index=idx,
                    action=sa.action,
                    is_ground_truth_violation=sa.is_violation,
                    pre_decision=None,
                    executed=executed,
                    tool_call=ToolCall(
                        call_id=f"base_call_{idx+1}",
                        tool_name=sa.action.tool_name or "tool",
                        arguments=_extract_arguments(sa.action),
                    ),
                    tool_result=ToolResult(
                        call_id=f"base_call_{idx+1}",
                        status=outcome.status,
                        output=outcome.output,
                        error=outcome.error,
                        exit_code=outcome.exit_code,
                        duration_ms=outcome.duration_ms,
                        metadata=outcome.metadata,
                    ),
                    post_decision=None,
                    was_violation_executed=was_violation_exec,
                    was_violation_prevented=False,
                    was_false_blocked=False,
                )
            )

        # Baseline accepts all completion claims blindly
        accepted_claims = list(scenario.completion_claims)
        unsupported_accepted = 0
        gt_supported = set(scenario.ground_truth_supported_claims)

        for c in accepted_claims:
            if c.claim_id not in gt_supported:
                unsupported_accepted += 1

        variant_claimed_success = True
        actual_success = (
            scenario.expected_task_success
            and violating_executed == 0
            and unsupported_accepted == 0
        )

        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            variant=BenchmarkVariant.BASELINE,
            iteration=iteration,
            records=tuple(records),
            claim_evaluations=(),
            accepted_claims=tuple(accepted_claims),
            variant_claimed_success=variant_claimed_success,
            actual_task_success=actual_success,
            violating_actions_attempted=violating_attempted,
            violating_actions_executed=violating_executed,
            non_violating_actions_attempted=non_violating_attempted,
            non_violating_actions_blocked=0,
            positive_claims_asserted=len(scenario.completion_claims),
            unsupported_claims_accepted=unsupported_accepted,
            total_tool_calls=total_calls,
            extra_tool_calls=extra_calls,
            trace_event_count=0,
        )

    def _run_specguard(self, scenario: BenchmarkScenario, iteration: int) -> ScenarioResult:
        """SPECGUARD: pre/post SpecGuard active; EvidenceGate disabled."""
        ledger = ConstraintLedger()
        for c in scenario.initial_constraints:
            ledger.add(c)
        guard = SpecGuard(ledger=ledger)

        records: list[ScenarioExecutionRecord] = []
        violating_attempted = 0
        violating_executed = 0
        non_violating_attempted = 0
        non_violating_blocked = 0
        total_calls = 0
        extra_calls = 0
        any_blocked = False

        for idx, sa in enumerate(scenario.scripted_actions):
            if sa.is_violation:
                violating_attempted += 1
            else:
                non_violating_attempted += 1

            pre_dec = guard.evaluate(sa.action)
            executed = False
            tool_call = None
            tool_result = None
            post_dec = None
            was_viol_exec = False
            was_viol_prev = False
            was_false_blk = False

            if pre_dec.is_blocked:
                any_blocked = True
                if sa.is_violation:
                    was_viol_prev = True
                else:
                    was_false_blk = True
                    non_violating_blocked += 1
            else:
                executed = True
                total_calls += 1
                outcome = sa.get_outcome()

                tool_call = ToolCall(
                    call_id=f"sg_call_{idx+1}",
                    tool_name=sa.action.tool_name or "tool",
                    arguments=_extract_arguments(sa.action),
                )
                tool_result = ToolResult(
                    call_id=f"sg_call_{idx+1}",
                    status=outcome.status,
                    output=outcome.output,
                    error=outcome.error,
                    exit_code=outcome.exit_code,
                    duration_ms=outcome.duration_ms,
                    metadata=outcome.metadata,
                )

                obs = ActionObservation.from_tool_result(
                    tool_result=tool_result,
                    changed_paths=outcome.changed_paths,
                    accessed_paths=outcome.accessed_paths,
                    tool_name=outcome.tool_name or sa.action.tool_name,
                    action_kind=outcome.action_kind or sa.action.action_kind,
                    target_type=outcome.target_type or sa.action.target_type,
                    context=outcome.metadata,
                )
                post_dec = guard.evaluate_post_action(sa.action, observation=obs)

                if post_dec.is_blocked:
                    any_blocked = True
                    if sa.is_violation:
                        was_viol_exec = True
                        violating_executed += 1
                        extra_calls += 1
                    else:
                        was_false_blk = True
                        non_violating_blocked += 1
                else:
                    if sa.is_violation:
                        was_viol_exec = True
                        violating_executed += 1
                        extra_calls += 1

            records.append(
                ScenarioExecutionRecord(
                    step_index=idx,
                    action=sa.action,
                    is_ground_truth_violation=sa.is_violation,
                    pre_decision=pre_dec,
                    executed=executed,
                    tool_call=tool_call,
                    tool_result=tool_result,
                    post_decision=post_dec,
                    was_violation_executed=was_viol_exec,
                    was_violation_prevented=was_viol_prev,
                    was_false_blocked=was_false_blk,
                )
            )

        # EvidenceGate disabled: if not blocked, accept claims
        accepted_claims: list[Claim] = []
        unsupported_accepted = 0
        gt_supported = set(scenario.ground_truth_supported_claims)

        if not any_blocked:
            accepted_claims = list(scenario.completion_claims)
            for c in accepted_claims:
                if c.claim_id not in gt_supported:
                    unsupported_accepted += 1

        variant_claimed_success = not any_blocked
        actual_success = (
            scenario.expected_task_success
            and not any_blocked
            and violating_executed == 0
            and unsupported_accepted == 0
        )

        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            variant=BenchmarkVariant.SPECGUARD,
            iteration=iteration,
            records=tuple(records),
            claim_evaluations=(),
            accepted_claims=tuple(accepted_claims),
            variant_claimed_success=variant_claimed_success,
            actual_task_success=actual_success,
            violating_actions_attempted=violating_attempted,
            violating_actions_executed=violating_executed,
            non_violating_actions_attempted=non_violating_attempted,
            non_violating_actions_blocked=non_violating_blocked,
            positive_claims_asserted=len(scenario.completion_claims),
            unsupported_claims_accepted=unsupported_accepted,
            total_tool_calls=total_calls,
            extra_tool_calls=extra_calls,
            trace_event_count=0,
        )

    def _run_evidencegate(self, scenario: BenchmarkScenario, iteration: int) -> ScenarioResult:
        """EVIDENCEGATE: no SpecGuard blocking, trace store and EvidenceGate active."""
        trace_store = TraceStore()
        trace_id = f"eg-trace-{scenario.scenario_id}-{iteration}"
        gate = EvidenceGate()

        records: list[ScenarioExecutionRecord] = []
        violating_attempted = 0
        violating_executed = 0
        non_violating_attempted = 0
        total_calls = 0
        extra_calls = 0

        seq = 0
        for idx, sa in enumerate(scenario.scripted_actions):
            if sa.is_violation:
                violating_attempted += 1
            else:
                non_violating_attempted += 1

            outcome = sa.get_outcome()
            executed = True
            total_calls += 1

            was_viol_exec = False
            if sa.is_violation:
                was_viol_exec = True
                violating_executed += 1
                extra_calls += 1

            call_id = f"call_{idx+1:03d}"
            tool_call = ToolCall(
                call_id=call_id,
                tool_name=sa.action.tool_name or "tool",
                arguments=_extract_arguments(sa.action),
            )
            tool_result = ToolResult(
                call_id=call_id,
                status=outcome.status,
                output=outcome.output,
                error=outcome.error,
                exit_code=outcome.exit_code,
                duration_ms=outcome.duration_ms,
                metadata=outcome.metadata,
            )

            # Append TOOL_CALL event
            evt_call = TraceEvent(
                event_id=f"evt_call_{idx+1:03d}",
                trace_id=trace_id,
                sequence=seq,
                actor=ActorKind.AGENT,
                event_kind=EventKind.TOOL_CALL,
                payload=tool_call,
            )
            trace_store.append(evt_call)
            seq += 1

            # Append TOOL_RESULT event
            evt_res = TraceEvent(
                event_id=f"evt_res_{idx+1:03d}",
                trace_id=trace_id,
                sequence=seq,
                actor=ActorKind.SYSTEM,
                event_kind=EventKind.TOOL_RESULT,
                payload=tool_result,
                parent_id=evt_call.event_id,
            )
            trace_store.append(evt_res)
            seq += 1

            records.append(
                ScenarioExecutionRecord(
                    step_index=idx,
                    action=sa.action,
                    is_ground_truth_violation=sa.is_violation,
                    pre_decision=None,
                    executed=executed,
                    tool_call=tool_call,
                    tool_result=tool_result,
                    post_decision=None,
                    was_violation_executed=was_viol_exec,
                    was_violation_prevented=False,
                    was_false_blocked=False,
                )
            )

        # Evaluate completion claims against EvidenceGate
        evaluations = [
            gate.evaluate(c.model_copy(update={"trace_id": trace_id}), trace_store)
            for c in scenario.completion_claims
        ]
        accepted_claims = [ev.claim for ev in evaluations if ev.verdict == ClaimVerdict.VERIFIED]

        gt_supported = set(scenario.ground_truth_supported_claims)
        unsupported_accepted = 0
        for c in accepted_claims:
            if c.claim_id not in gt_supported:
                unsupported_accepted += 1

        all_claims_verified = (
            len(accepted_claims) == len(scenario.completion_claims)
            if scenario.completion_claims
            else True
        )
        variant_claimed_success = all_claims_verified
        actual_success = (
            scenario.expected_task_success
            and all_claims_verified
            and violating_executed == 0
            and unsupported_accepted == 0
        )

        trace_events = trace_store.list_events(trace_id)

        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            variant=BenchmarkVariant.EVIDENCEGATE,
            iteration=iteration,
            records=tuple(records),
            claim_evaluations=tuple(evaluations),
            accepted_claims=tuple(accepted_claims),
            variant_claimed_success=variant_claimed_success,
            actual_task_success=actual_success,
            violating_actions_attempted=violating_attempted,
            violating_actions_executed=violating_executed,
            non_violating_actions_attempted=non_violating_attempted,
            non_violating_actions_blocked=0,
            positive_claims_asserted=len(scenario.completion_claims),
            unsupported_claims_accepted=unsupported_accepted,
            total_tool_calls=total_calls,
            extra_tool_calls=extra_calls,
            trace_event_count=len(trace_events),
        )

    def _run_full(self, scenario: BenchmarkScenario, iteration: int) -> ScenarioResult:
        """FULL_AGENTCONTRACT: SpecGuard + trace + EvidenceGate integrated via runtime."""
        trace_id = f"full-trace-{scenario.scenario_id}-{iteration}"
        runtime = AgentContractRuntime(
            trace_id=trace_id,
            record_all_guard_decisions=True,
            id_generator=IdGenerator(prefix="full_", deterministic=True),
        )
        for c in scenario.initial_constraints:
            runtime.add_constraint(c)

        records: list[ScenarioExecutionRecord] = []
        violating_attempted = 0
        violating_executed = 0
        non_violating_attempted = 0
        non_violating_blocked = 0
        total_calls = 0
        extra_calls = 0
        any_blocked = False

        for idx, sa in enumerate(scenario.scripted_actions):
            if sa.is_violation:
                violating_attempted += 1
            else:
                non_violating_attempted += 1

            def _executor(action: Action, tool_call: ToolCall) -> ToolExecutionOutcome:
                return sa.get_outcome()

            res = runtime.execute(sa.action, executor=_executor)

            was_viol_exec = False
            was_viol_prev = False
            was_false_blk = False

            if res.is_blocked:
                any_blocked = True
                if sa.is_violation:
                    was_viol_prev = True
                else:
                    was_false_blk = True
                    non_violating_blocked += 1
            else:
                total_calls += 1
                if res.is_post_blocked:
                    any_blocked = True
                    if sa.is_violation:
                        was_viol_exec = True
                        violating_executed += 1
                        extra_calls += 1
                    else:
                        was_false_blk = True
                        non_violating_blocked += 1
                else:
                    if sa.is_violation:
                        was_viol_exec = True
                        violating_executed += 1
                        extra_calls += 1

            records.append(
                ScenarioExecutionRecord(
                    step_index=idx,
                    action=sa.action,
                    is_ground_truth_violation=sa.is_violation,
                    pre_decision=res.pre_decision,
                    executed=res.executed,
                    tool_call=res.tool_call,
                    tool_result=res.tool_result,
                    post_decision=res.post_decision,
                    was_violation_executed=was_viol_exec,
                    was_violation_prevented=was_viol_prev,
                    was_false_blocked=was_false_blk,
                )
            )

        # Scoped claim verification
        claims_with_scope = [
            c.model_copy(update={"trace_id": trace_id}) for c in scenario.completion_claims
        ]
        verification = runtime.verify_claims(claims_with_scope)
        evaluations = verification.evaluations
        accepted_claims: list[Claim] = []
        if not any_blocked:
            accepted_claims = [ev.claim for ev in evaluations if ev.verdict == ClaimVerdict.VERIFIED]

        gt_supported = set(scenario.ground_truth_supported_claims)
        unsupported_accepted = 0
        for c in accepted_claims:
            if c.claim_id not in gt_supported:
                unsupported_accepted += 1

        all_claims_verified = (
            len(accepted_claims) == len(scenario.completion_claims)
            if scenario.completion_claims
            else True
        )

        variant_claimed_success = (not any_blocked) and all_claims_verified
        actual_success = (
            scenario.expected_task_success
            and (not any_blocked)
            and all_claims_verified
            and violating_executed == 0
            and unsupported_accepted == 0
        )

        trace_events = runtime.trace_store.list_events(trace_id)

        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            variant=BenchmarkVariant.FULL_AGENTCONTRACT,
            iteration=iteration,
            records=tuple(records),
            claim_evaluations=evaluations,
            accepted_claims=tuple(accepted_claims),
            variant_claimed_success=variant_claimed_success,
            actual_task_success=actual_success,
            violating_actions_attempted=violating_attempted,
            violating_actions_executed=violating_executed,
            non_violating_actions_attempted=non_violating_attempted,
            non_violating_actions_blocked=non_violating_blocked,
            positive_claims_asserted=len(scenario.completion_claims),
            unsupported_claims_accepted=unsupported_accepted,
            total_tool_calls=total_calls,
            extra_tool_calls=extra_calls,
            trace_event_count=len(trace_events),
        )

    def run(
        self,
        scenarios: Sequence[BenchmarkScenario] | None = None,
        variants: Sequence[BenchmarkVariant] | None = None,
        repetitions: int = 1,
    ) -> BenchmarkReport:
        """Run all benchmark scenarios across requested variants and generate a report."""
        if scenarios is None:
            scenarios = get_standard_scenarios()
        if variants is None:
            variants = (
                BenchmarkVariant.BASELINE,
                BenchmarkVariant.SPECGUARD,
                BenchmarkVariant.EVIDENCEGATE,
                BenchmarkVariant.FULL_AGENTCONTRACT,
            )

        run_id = f"{self._id_prefix}{uuid.uuid4().hex[:8]}"
        all_results: list[ScenarioResult] = []
        results_by_variant: dict[BenchmarkVariant, list[ScenarioResult]] = {
            v: [] for v in variants
        }

        for var in variants:
            for rep in range(1, repetitions + 1):
                for scen in scenarios:
                    res = self.run_scenario(scen, var, iteration=rep)
                    all_results.append(res)
                    results_by_variant[var].append(res)

        # Compute baseline latency for overhead comparison
        baseline_latency: float | None = None
        if BenchmarkVariant.BASELINE in results_by_variant:
            b_results = results_by_variant[BenchmarkVariant.BASELINE]
            if b_results:
                baseline_latency = sum(r.duration_ms for r in b_results) / len(b_results)

        # Aggregate metrics
        metrics: dict[BenchmarkVariant, BenchmarkMetrics] = {}
        for var in variants:
            m = BenchmarkMetrics.compute(
                variant=var,
                results=results_by_variant[var],
                baseline_avg_latency_ms=baseline_latency if var != BenchmarkVariant.BASELINE else None,
            )
            metrics[var] = m

        return BenchmarkReport(
            run_id=run_id,
            created_at=datetime.now(timezone.utc),
            repetitions=repetitions,
            scenario_count=len(scenarios),
            metrics=metrics,
            scenario_results=tuple(all_results),
        )
