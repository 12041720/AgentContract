"""Deterministic EvidenceGate verifying agent claims against trace store evidence."""

from collections.abc import Iterable, Mapping
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
    """Deterministically check if a ToolCall satisfies the identifiers on a Claim."""
    if claim.call_id is not None and tc.call_id != claim.call_id:
        return False
    if claim.tool_name is not None and tc.tool_name.strip().lower() != claim.tool_name.strip().lower():
        return False
    if claim.command is not None:
        if not _command_in_tool_call(tc, claim.command):
            return False
    return True


def _file_matches_tool_result(tr: ToolResult, target_path: str) -> tuple[bool, bool]:
    """Check if target_path is confirmed or contradicted in a ToolResult output or metadata.

    Returns:
        (is_present, is_contradicted)
    """
    norm_target = target_path.strip().replace("\\", "/")

    # Check output
    output = tr.output
    if output is not None:
        # Mapping output
        if isinstance(output, Mapping):
            for k in ("files", "created", "modified", "paths", "artifacts"):
                if k in output:
                    val = output[k]
                    if isinstance(val, (list, tuple)):
                        for item in val:
                            if str(item).strip().replace("\\", "/") == norm_target:
                                return True, False
            for k in ("file", "path", "target"):
                if k in output and str(output[k]).strip().replace("\\", "/") == norm_target:
                    if output.get("exists") is False:
                        return False, True
                    return True, False
            if output.get("exists") is False:
                return False, True

        # String or list output
        elif isinstance(output, (list, tuple)):
            for item in output:
                if str(item).strip().replace("\\", "/") == norm_target:
                    return True, False
        elif isinstance(output, str):
            if norm_target in output.replace("\\", "/"):
                return True, False

    # Check metadata
    if "changed_paths" in tr.metadata:
        cp = tr.metadata["changed_paths"]
        if isinstance(cp, (list, tuple)):
            for p in cp:
                if str(p).strip().replace("\\", "/") == norm_target:
                    return True, False

    return False, False


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
    """

    def __init__(self, graph: EvidenceGraph | None = None) -> None:
        self._graph = graph if graph is not None else EvidenceGraph()

    @property
    def graph(self) -> EvidenceGraph:
        """The underlying evidence graph indexing all evaluated claims and references."""
        return self._graph

    def evaluate(self, claim: Claim, trace_store: TraceStore) -> ClaimEvaluation:
        """Evaluate a single claim against events stored in the TraceStore."""
        # 1. Gather candidate events filtered by trace_id and session_id if specified on the claim
        events = trace_store.list_events(trace_id=claim.trace_id)
        if claim.session_id is not None:
            events = tuple(e for e in events if e.session_id == claim.session_id)

        # Map call_id -> ToolCall event for correlating results
        tool_call_events: dict[str, TraceEvent] = {}
        tool_result_events: list[TraceEvent] = []

        for e in events:
            # Rule 1: AGENT_MESSAGE is never evidence by itself
            if e.event_kind == EventKind.AGENT_MESSAGE:
                continue

            if e.event_kind == EventKind.TOOL_CALL and e.tool_call is not None:
                tool_call_events[e.tool_call.call_id] = e
            elif e.event_kind == EventKind.TOOL_RESULT and e.tool_result is not None:
                tool_result_events.append(e)

        supporting: list[EvidenceRef] = []
        contradicting: list[EvidenceRef] = []
        reason_notes: list[str] = []

        # 2. Evaluate claim based on claim_type
        if claim.claim_type == ClaimType.TOOL_SUCCEEDED:
            matching_results = self._filter_tool_results_for_claim(
                tool_result_events, tool_call_events, claim
            )
            if not matching_results:
                reason = f"No matching ToolResult evidence found for claim '{claim.claim_id}'."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

            for res_evt in matching_results:
                tr = res_evt.tool_result
                assert tr is not None
                if tr.status == ToolResultStatus.SUCCESS:
                    if claim.expected_exit_code is not None and tr.exit_code != claim.expected_exit_code:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.CONTRADICTS,
                            reason=f"ToolResult exit_code {tr.exit_code} != expected {claim.expected_exit_code}.",
                        )
                        contradicting.append(ref)
                        reason_notes.append(ref.reason or "")
                    else:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.SUPPORTS,
                            reason=f"ToolResult completed successfully with status SUCCESS (exit_code={tr.exit_code}).",
                        )
                        supporting.append(ref)
                        reason_notes.append(ref.reason or "")
                else:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"ToolResult failed with status {tr.status.value}: {tr.error or 'error'}.",
                    )
                    contradicting.append(ref)
                    reason_notes.append(ref.reason or "")

        elif claim.claim_type == ClaimType.COMMAND_EXITED_ZERO:
            matching_results = self._filter_tool_results_for_claim(
                tool_result_events, tool_call_events, claim
            )
            if not matching_results:
                reason = f"No matching command ToolResult found for claim '{claim.claim_id}'."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

            for res_evt in matching_results:
                tr = res_evt.tool_result
                assert tr is not None
                if tr.status == ToolResultStatus.SUCCESS and tr.exit_code == 0:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.SUPPORTS,
                        reason="Command execution completed successfully with exit code 0.",
                    )
                    supporting.append(ref)
                    reason_notes.append(ref.reason or "")
                elif tr.exit_code is not None and tr.exit_code != 0:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Command execution completed with non-zero exit code {tr.exit_code}.",
                    )
                    contradicting.append(ref)
                    reason_notes.append(ref.reason or "")
                elif tr.status in (ToolResultStatus.ERROR, ToolResultStatus.TIMEOUT, ToolResultStatus.CANCELLED):
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Command execution failed with status {tr.status.value}: {tr.error or 'failure'}.",
                    )
                    contradicting.append(ref)
                    reason_notes.append(ref.reason or "")
                else:
                    # Missing exit_code cannot verify exit_code == 0
                    reason_notes.append(f"ToolResult for call '{tr.call_id}' did not record an exit_code.")

        elif claim.claim_type == ClaimType.TESTS_PASSED:
            matching_results = self._filter_tool_results_for_claim(
                tool_result_events, tool_call_events, claim
            )
            if not matching_results:
                reason = f"No test execution ToolResult evidence found for claim '{claim.claim_id}'."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

            for res_evt in matching_results:
                tr = res_evt.tool_result
                assert tr is not None
                # Check for explicit contradiction: non-success or non-zero exit
                if tr.status in (ToolResultStatus.ERROR, ToolResultStatus.TIMEOUT, ToolResultStatus.CANCELLED):
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Test execution failed with status {tr.status.value}: {tr.error or 'error'}.",
                    )
                    contradicting.append(ref)
                    reason_notes.append(ref.reason or "")
                elif tr.exit_code is not None and tr.exit_code != 0:
                    ref = EvidenceRef.from_event(
                        res_evt,
                        relation=EvidenceRelation.CONTRADICTS,
                        reason=f"Test execution exited with failure code {tr.exit_code}.",
                    )
                    contradicting.append(ref)
                    reason_notes.append(ref.reason or "")
                elif tr.status == ToolResultStatus.SUCCESS and (tr.exit_code == 0 or tr.exit_code is None):
                    if claim.expected_exit_code is not None and tr.exit_code != claim.expected_exit_code:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.CONTRADICTS,
                            reason=f"Test exit code {tr.exit_code} != expected {claim.expected_exit_code}.",
                        )
                        contradicting.append(ref)
                        reason_notes.append(ref.reason or "")
                    else:
                        ref = EvidenceRef.from_event(
                            res_evt,
                            relation=EvidenceRelation.SUPPORTS,
                            reason=f"Test execution succeeded with status SUCCESS (exit_code={tr.exit_code}).",
                        )
                        supporting.append(ref)
                        reason_notes.append(ref.reason or "")
                else:
                    reason_notes.append(f"Inconclusive test ToolResult for call '{tr.call_id}'.")

        elif claim.claim_type == ClaimType.FILE_EXISTS:
            if not claim.target_path:
                reason = f"FILE_EXISTS claim '{claim.claim_id}' is missing required target_path."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

            # Check all tool results and state observations in candidate events
            matched_any = False
            for e in events:
                if e.event_kind == EventKind.TOOL_RESULT and e.tool_result is not None:
                    tr = e.tool_result
                    # If claim specifies call_id, filter by call_id
                    if claim.call_id is not None and tr.call_id != claim.call_id:
                        continue

                    is_present, is_contra = _file_matches_tool_result(tr, claim.target_path)
                    if is_present:
                        matched_any = True
                        if tr.status == ToolResultStatus.SUCCESS:
                            ref = EvidenceRef.from_event(
                                e,
                                relation=EvidenceRelation.SUPPORTS,
                                reason=f"ToolResult for '{tr.call_id}' confirmed existence/creation of '{claim.target_path}'.",
                            )
                            supporting.append(ref)
                        else:
                            ref = EvidenceRef.from_event(
                                e,
                                relation=EvidenceRelation.CONTRADICTS,
                                reason=f"ToolResult for '{tr.call_id}' referenced '{claim.target_path}' but execution status is {tr.status.value}.",
                            )
                            contradicting.append(ref)
                    elif is_contra:
                        matched_any = True
                        ref = EvidenceRef.from_event(
                            e,
                            relation=EvidenceRelation.CONTRADICTS,
                            reason=f"ToolResult for '{tr.call_id}' reported '{claim.target_path}' does not exist.",
                        )
                        contradicting.append(ref)

            if not matched_any:
                reason = f"No trace evidence confirming existence of file '{claim.target_path}'."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

        elif claim.claim_type in (ClaimType.ACTION_COMPLETED, ClaimType.GENERIC):
            matching_results = self._filter_tool_results_for_claim(
                tool_result_events, tool_call_events, claim
            )
            if not matching_results:
                reason = f"No matching execution evidence found for claim '{claim.claim_id}'."
                return self._finalize_evaluation(claim, ClaimVerdict.UNVERIFIED, (), (), reason)

            for res_evt in matching_results:
                tr = res_evt.tool_result
                assert tr is not None
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

        # 3. Apply deterministic verdict precedence: Contradiction beats support
        if contradicting:
            verdict = ClaimVerdict.CONTRADICTED
            reason = "Claim is CONTRADICTED by trace evidence: " + "; ".join(
                r.reason for r in contradicting if r.reason
            )
        elif supporting:
            verdict = ClaimVerdict.VERIFIED
            reason = "Claim is VERIFIED by trace evidence: " + "; ".join(
                r.reason for r in supporting if r.reason
            )
        else:
            verdict = ClaimVerdict.UNVERIFIED
            reason = "Claim is UNVERIFIED: insufficient supporting evidence in trace."

        return self._finalize_evaluation(
            claim=claim,
            verdict=verdict,
            supporting=tuple(supporting),
            contradicting=tuple(contradicting),
            reason=reason,
        )

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

    def _filter_tool_results_for_claim(
        self,
        results: list[TraceEvent],
        calls: dict[str, TraceEvent],
        claim: Claim,
    ) -> list[TraceEvent]:
        """Filter ToolResult events to those matching the criteria of the Claim."""
        matched: list[TraceEvent] = []
        for r_evt in results:
            tr = r_evt.tool_result
            if tr is None:
                continue

            # Exact call_id check
            if claim.call_id is not None:
                if tr.call_id != claim.call_id:
                    continue

            # Tool call matching (tool_name, command)
            if claim.call_id is None and (claim.tool_name is not None or claim.command is not None):
                call_evt = calls.get(tr.call_id)
                if call_evt is None or call_evt.tool_call is None:
                    continue
                if not _tool_call_matches_claim(call_evt.tool_call, claim):
                    continue

            matched.append(r_evt)
        return matched

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
