"""Deterministic EvidenceGate verifying agent claims against trace store evidence."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

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
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
)
from agentcontract.trace.store import TraceStore


def _command_in_tool_call(tc: ToolCall, command: str) -> bool:
    """Check if a tool call argument matches the specified command string."""
    target_cmd = command.strip()
    args = tc.arguments
    for key in ("cmd", "command", "args", "script", "code"):
        if key in args:
            val = str(args[key]).strip()
            if val == target_cmd or val.startswith(target_cmd):
                return True
    return False


def _tool_call_matches_claim(tc: ToolCall, claim: Claim) -> bool:
    """Deterministically check if a ToolCall satisfies all selectors on a Claim conjunctively."""
    if claim.call_id is not None and tc.call_id != claim.call_id:
        return False
    if claim.tool_name is not None and tc.tool_name.strip().lower() != claim.tool_name.strip().lower():
        return False
    if claim.command is not None and not _command_in_tool_call(tc, claim.command):
        return False
    return True


def _check_file_exists_in_event(event: TraceEvent, target_path: str) -> tuple[bool, bool]:
    """Check explicit structured artifact/state observations for target_path.

    Returns:
        (supports, contradicts)
    """
    norm_target = target_path.strip().replace("\\", "/")
    candidate_mappings: list[Mapping[str, Any]] = []
    can_support = True
    if event.event_kind == EventKind.TOOL_RESULT and event.tool_result is not None:
        tr = event.tool_result
        if tr.status != ToolResultStatus.SUCCESS:
            can_support = False
        if isinstance(tr.output, Mapping):
            candidate_mappings.append(tr.output)
        if isinstance(tr.metadata, Mapping):
            candidate_mappings.append(tr.metadata)

    elif event.event_kind == EventKind.STATE_OBSERVATION:
        if isinstance(event.payload, Mapping):
            candidate_mappings.append(event.payload)
        if isinstance(event.metadata, Mapping):
            candidate_mappings.append(event.metadata)

    supports = False
    contradicts = False

    for m in candidate_mappings:
        # 1. Matching exact {"path": target, "exists": true / false}
        for key in ("path", "target", "file"):
            if key in m:
                val = str(m[key]).strip().replace("\\", "/")
                if val == norm_target:
                    if "exists" in m:
                        if m["exists"] is True and can_support:
                            supports = True
                        elif m["exists"] is False:
                            contradicts = True

        # 2. Explicit created_paths / existing_paths
        for key in ("created_paths", "existing_paths", "changed_paths", "files"):
            if key in m and isinstance(m[key], (list, tuple)) and can_support:
                for item in m[key]:
                    if str(item).strip().replace("\\", "/") == norm_target:
                        supports = True

        # 3. Explicit missing_paths / deleted_paths
        for key in ("missing_paths", "deleted_paths", "not_found"):
            if key in m and isinstance(m[key], (list, tuple)):
                for item in m[key]:
                    if str(item).strip().replace("\\", "/") == norm_target:
                        contradicts = True

    return supports, contradicts


def _resolve_single_tool_execution(
    calls: dict[str, TraceEvent],
    results: dict[str, TraceEvent],
    claim: Claim,
) -> tuple[TraceEvent | None, str | None]:
    """Deterministically resolve an execution claim to exactly one ToolResult event.

    Returns:
        (matching_result_event, error_reason)
    """
    # Trace ID is required for execution-backed claims
    if claim.trace_id is None:
        return None, f"Execution claim '{claim.claim_id}' must specify a trace_id for deterministic verification."

    # At least one selector must be provided
    has_selector = (claim.call_id is not None) or (claim.tool_name is not None) or (claim.command is not None)
    if not has_selector:
        return None, f"Execution claim '{claim.claim_id}' lacks deterministic execution selectors (call_id, tool_name, or command)."

    # If call_id is specified, find that specific call and validate all other selectors conjunctively
    if claim.call_id is not None:
        call_evt = calls.get(claim.call_id)
        if call_evt is None or call_evt.tool_call is None:
            return None, f"No ToolCall found for call_id '{claim.call_id}' in trace '{claim.trace_id}'."

        tc = call_evt.tool_call
        if claim.tool_name is not None and tc.tool_name.strip().lower() != claim.tool_name.strip().lower():
            return None, (
                f"ToolCall '{claim.call_id}' tool_name '{tc.tool_name}' does not match "
                f"claimed tool_name '{claim.tool_name}'."
            )
        if claim.command is not None and not _command_in_tool_call(tc, claim.command):
            return None, (
                f"ToolCall '{claim.call_id}' arguments do not match "
                f"claimed command '{claim.command}'."
            )

        res_evt = results.get(claim.call_id)
        if res_evt is None or res_evt.tool_result is None:
            return None, f"No matching ToolResult recorded for ToolCall '{claim.call_id}' in trace '{claim.trace_id}'."

        return res_evt, None

    # If call_id is NOT specified, resolve via tool_name and/or command
    matched_calls: list[TraceEvent] = []
    for call_evt in calls.values():
        tc = call_evt.tool_call
        if tc is None:
            continue
        if _tool_call_matches_claim(tc, claim):
            matched_calls.append(call_evt)

    if not matched_calls:
        return None, f"No ToolCall matching selectors found in trace '{claim.trace_id}'."

    if len(matched_calls) > 1:
        call_ids = [c.tool_call.call_id for c in matched_calls if c.tool_call]
        return None, (
            f"Ambiguous claim '{claim.claim_id}': resolved to {len(matched_calls)} matching executions "
            f"in trace '{claim.trace_id}' ({', '.join(call_ids)}). Claims must resolve to exactly one execution."
        )

    single_call = matched_calls[0]
    assert single_call.tool_call is not None
    cid = single_call.tool_call.call_id
    res_evt = results.get(cid)
    if res_evt is None or res_evt.tool_result is None:
        return None, f"No matching ToolResult recorded for matching ToolCall '{cid}' in trace '{claim.trace_id}'."

    return res_evt, None


class EvidenceGate:
    """Deterministic verification gate evaluating agent claims against trace evidence.

    Invariants enforced:
    1. Agent statements (AGENT_MESSAGE) are never evidence by themselves.
    2. Missing evidence always yields UNVERIFIED.
    3. Explicit contradictory evidence yields CONTRADICTED.
    4. Matching deterministic success evidence yields VERIFIED.
    5. ERROR, TIMEOUT, or CANCELLED tool results cannot verify success.
    6. For exit-code claims, only an observed matching result with exit_code == 0 verifies success.
    7. Evidence from another trace or call_id cannot satisfy a specific claim.
    8. Precedence: Contradiction dominates support for the same execution.
    9. Generic semantic claims are never verified by deterministic EvidenceGate.
    10. Execution claims must resolve to exactly one execution; ambiguous or unscoped claims are UNVERIFIED.
    """

    def __init__(self, graph: EvidenceGraph | None = None) -> None:
        self._graph = graph if graph is not None else EvidenceGraph()

    @property
    def graph(self) -> EvidenceGraph:
        """The underlying evidence graph indexing all evaluated claims and references."""
        return self._graph

    def evaluate(self, claim: Claim, trace_store: TraceStore) -> ClaimEvaluation:
        """Evaluate a single claim against events stored in the TraceStore."""
        # Rule: GENERIC semantic claims must never be verified by deterministic EvidenceGate
        if claim.claim_type == ClaimType.GENERIC:
            reason = (
                f"Claim '{claim.claim_id}' has type GENERIC: arbitrary semantic prose claims "
                "cannot be verified by deterministic EvidenceGate."
            )
            return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

        # Scoped claims require a trace_id; do not search across all traces
        if claim.trace_id is None:
            reason = f"Claim '{claim.claim_id}' must specify a trace_id for deterministic verification."
            return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

        # 1. Gather candidate events filtered by trace_id and session_id if specified
        events = trace_store.list_events(trace_id=claim.trace_id)
        if claim.session_id is not None:
            events = tuple(e for e in events if e.session_id == claim.session_id)

        tool_call_events: dict[str, TraceEvent] = {}
        tool_result_events_by_call: dict[str, TraceEvent] = {}

        for e in events:
            # Rule 1: AGENT_MESSAGE is never evidence by itself
            if e.event_kind == EventKind.AGENT_MESSAGE:
                continue

            if e.event_kind == EventKind.TOOL_CALL and e.tool_call is not None:
                tool_call_events[e.tool_call.call_id] = e
            elif e.event_kind == EventKind.TOOL_RESULT and e.tool_result is not None:
                tool_result_events_by_call[e.tool_result.call_id] = e

        supporting: list[EvidenceRef] = []
        contradicting: list[EvidenceRef] = []

        # 2. Evaluate claim based on claim_type
        if claim.claim_type in (
            ClaimType.TOOL_SUCCEEDED,
            ClaimType.COMMAND_EXITED_ZERO,
            ClaimType.TESTS_PASSED,
            ClaimType.ACTION_COMPLETED,
        ):
            res_evt, err_reason = _resolve_single_tool_execution(
                tool_call_events, tool_result_events_by_call, claim
            )
            if res_evt is None or res_evt.tool_result is None:
                return self._finalize_evaluation(
                    claim,
                    ClaimVerdict.UNVERIFIED,
                    (),
                    (),
                    err_reason or f"Execution for claim '{claim.claim_id}' could not be resolved.",
                )

            tr = res_evt.tool_result

            if claim.claim_type == ClaimType.TOOL_SUCCEEDED:
                if tr.status == ToolResultStatus.SUCCESS:
                    if claim.expected_exit_code is not None and tr.exit_code != claim.expected_exit_code:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.CONTRADICTS,
                            reason=f"ToolResult exit_code {tr.exit_code} != expected {claim.expected_exit_code}.",
                        )
                        contradicting.append(ref)
                    else:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.SUPPORTS,
                            reason=f"ToolResult completed successfully with status SUCCESS (exit_code={tr.exit_code}).",
                        )
                        supporting.append(ref)
                else:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"ToolResult failed with status {tr.status.value}: {tr.error or 'error'}.",
                    )
                    contradicting.append(ref)

            elif claim.claim_type == ClaimType.COMMAND_EXITED_ZERO:
                if tr.status == ToolResultStatus.SUCCESS and tr.exit_code == 0:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.SUPPORTS,
                        reason="Command execution completed successfully with exit code 0.",
                    )
                    supporting.append(ref)
                elif tr.exit_code is not None and tr.exit_code != 0:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Command execution completed with non-zero exit code {tr.exit_code}.",
                    )
                    contradicting.append(ref)
                elif tr.status in (ToolResultStatus.ERROR, ToolResultStatus.TIMEOUT, ToolResultStatus.CANCELLED):
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Command execution failed with status {tr.status.value}: {tr.error or 'failure'}.",
                    )
                    contradicting.append(ref)
                else:
                    # Missing exit_code cannot verify COMMAND_EXITED_ZERO
                    return self._finalize_evaluation(
                        claim,
                        ClaimVerdict.UNVERIFIED,
                        (),
                        (),
                        f"ToolResult for call '{tr.call_id}' did not record an exit_code.",
                    )

            elif claim.claim_type == ClaimType.TESTS_PASSED:
                if tr.status in (ToolResultStatus.ERROR, ToolResultStatus.TIMEOUT, ToolResultStatus.CANCELLED):
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Test execution failed with status {tr.status.value}: {tr.error or 'error'}.",
                    )
                    contradicting.append(ref)
                elif tr.exit_code is not None and tr.exit_code != 0:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Test execution exited with failure code {tr.exit_code}.",
                    )
                    contradicting.append(ref)
                elif tr.status == ToolResultStatus.SUCCESS and (tr.exit_code == 0 or tr.exit_code is None):
                    if claim.expected_exit_code is not None and tr.exit_code != claim.expected_exit_code:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.CONTRADICTS,
                            reason=f"Test exit code {tr.exit_code} != expected {claim.expected_exit_code}.",
                        )
                        contradicting.append(ref)
                    else:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.SUPPORTS,
                            reason=f"Test execution succeeded with status SUCCESS (exit_code={tr.exit_code}).",
                        )
                        supporting.append(ref)
                else:
                    return self._finalize_evaluation(
                        claim,
                        ClaimVerdict.UNVERIFIED,
                        (),
                        (),
                        f"Inconclusive test ToolResult for call '{tr.call_id}'.",
                    )

            elif claim.claim_type == ClaimType.ACTION_COMPLETED:
                if tr.status == ToolResultStatus.SUCCESS:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.SUPPORTS,
                        reason=f"Action result '{tr.call_id}' completed with status SUCCESS.",
                    )
                    supporting.append(ref)
                else:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Action result '{tr.call_id}' failed with status {tr.status.value}.",
                    )
                    contradicting.append(ref)

        elif claim.claim_type == ClaimType.FILE_EXISTS:
            if claim.trace_id is None:
                reason = f"FILE_EXISTS claim '{claim.claim_id}' must specify a trace_id."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

            if not claim.target_path:
                reason = f"FILE_EXISTS claim '{claim.claim_id}' is missing required target_path."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

            events_to_check = events
            if claim.call_id is not None:
                res = tool_result_events_by_call.get(claim.call_id)
                events_to_check = (res,) if res is not None else ()

            for e in events_to_check:
                is_sup, is_contra = _check_file_exists_in_event(e, claim.target_path)
                if is_contra:
                    ref = EvidenceRef.from_event(
                        e,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Event '{e.event_id}' confirms '{claim.target_path}' is missing or deleted.",
                    )
                    contradicting.append(ref)
                elif is_sup:
                    ref = EvidenceRef.from_event(
                        e,
                        relation=EvidenceRelation.SUPPORTS,
                        reason=f"Event '{e.event_id}' confirms existence/creation of '{claim.target_path}'.",
                    )
                    supporting.append(ref)

            if not supporting and not contradicting:
                reason = f"No trace evidence confirming existence of file '{claim.target_path}'."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

        # 3. Deterministic verdict precedence: Contradiction beats support
        verdict, reason = self.determine_verdict(supporting, contradicting)

        return self._finalize_evaluation(
            claim=claim,
            verdict=verdict,
            supporting=tuple(supporting),
            contradicting=tuple(contradicting),
            reason=reason,
        )

    @staticmethod
    def determine_verdict(
        supporting: Sequence[EvidenceRef],
        contradicting: Sequence[EvidenceRef],
    ) -> tuple[ClaimVerdict, str]:
        """Apply deterministic verdict precedence: Contradiction dominates support."""
        if contradicting:
            reason = "Claim is CONTRADICTED by trace evidence: " + "; ".join(
                r.reason for r in contradicting if r.reason
            )
            return ClaimVerdict.CONTRADICTED, reason
        if supporting:
            reason = "Claim is VERIFIED by trace evidence: " + "; ".join(
                r.reason for r in supporting if r.reason
            )
            return ClaimVerdict.VERIFIED, reason
        return ClaimVerdict.UNVERIFIED, "Claim is UNVERIFIED: insufficient supporting evidence in trace."

    def evaluate_many(
        self,
        claims: Iterable[Claim],
        trace_store: TraceStore,
    ) -> tuple[ClaimEvaluation, ...]:
        """Evaluate multiple claims sequentially and deterministically."""
        results: list[ClaimEvaluation] = []
        for claim in claims:
            eval_result = self.evaluate(claim, trace_store)
            results.append(eval_result)
        return tuple(results)

    def _finalize_evaluation(
        self,
        claim: Claim,
        verdict: ClaimVerdict,
        supporting: tuple[EvidenceRef, ...] | list[EvidenceRef],
        contradicting: tuple[EvidenceRef, ...] | list[EvidenceRef],
        reason: str,
    ) -> ClaimEvaluation:
        """Create ClaimEvaluation, register it in the evidence graph, and return it."""
        evaluation = ClaimEvaluation(
            claim=claim,
            verdict=verdict,
            supporting_evidence=tuple(supporting),
            contradicting_evidence=tuple(contradicting),
            reason=reason,
            evaluated_at=datetime.now(timezone.utc),
        )
        self._graph.add_evaluation(evaluation)
        return evaluation
