"""SpecGuard pre/post action deterministic validation engine."""

from collections.abc import Iterable, Mapping
import fnmatch
from typing import Any

from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.constraints.models import (
    Constraint,
    ConstraintScope,
    ConstraintStatus,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.guard.models import (
    Action,
    ActionKind,
    ActionObservation,
    DecisionKind,
    GuardDecision,
)
from agentcontract.trace.models import TracePointer


def _normalize_path_str(p: str) -> str:
    """Normalize a path string for cross-platform matching."""
    norm = p.strip().replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def _exact_value_equal(v1: Any, v2: Any) -> bool:
    """Exact value matching preserving type semantics (e.g. 1 != '1', True != 1, True != 'True')."""
    # In Python, bool is a subclass of int (True == 1), so explicitly prohibit bool vs non-bool equality
    if isinstance(v1, bool) or isinstance(v2, bool):
        if not (isinstance(v1, bool) and isinstance(v2, bool)):
            return False
        return v1 is v2

    # Distinct scalar types (e.g. int vs str, float vs str) must not be equal
    if type(v1) is not type(v2):
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            return v1 == v2
        return False

    return v1 == v2


def _dedup_ordered(items: Iterable[str]) -> tuple[str, ...]:
    """Deduplicate strings while preserving deterministic encounter order."""
    seen: set[str] = set()
    res: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            res.append(item)
    return tuple(res)


def match_scope(scope: ConstraintScope, action: Action) -> bool:
    """Deterministically check if an action matches all populated dimensions of a constraint scope.

    Matching rules:
    - Empty scope field means 'no restriction on that dimension' (matches everything).
    - Populated target_type must match action.target_type (case-insensitive).
    - Populated tools must contain action.tool_name (case-insensitive).
    - Populated actions must contain action.action_kind or action.operation.
    - Populated paths must match at least one path in action.paths (exact, directory prefix, or glob).
    - Populated selectors must match exact typed key/value pairs in action.context or action.payload.
    """
    # 1. Target Type dimension
    if scope.target_type is not None and scope.target_type.strip():
        if not action.target_type:
            return False
        if scope.target_type.strip().lower() != action.target_type.strip().lower():
            return False

    # 2. Tools dimension
    if scope.tools:
        if not action.tool_name:
            return False
        normalized_tools = {t.strip().lower() for t in scope.tools if t.strip()}
        if action.tool_name.strip().lower() not in normalized_tools:
            return False

    # 3. Actions dimension
    if scope.actions:
        normalized_scope_actions = {a.strip().lower() for a in scope.actions if a.strip()}
        action_candidates: set[str] = set()
        if action.action_kind:
            action_candidates.add(action.action_kind.value.lower())
            action_candidates.add(action.action_kind.name.lower())
            # Common verb mappings
            if action.action_kind in (ActionKind.FILE_WRITE, ActionKind.STATE_CHANGE):
                action_candidates.update({"write", "modify", "update", "create", "edit", "save"})
            elif action.action_kind == ActionKind.FILE_READ:
                action_candidates.update({"read", "view", "get", "open"})
            elif action.action_kind == ActionKind.FILE_DELETE:
                action_candidates.update({"delete", "remove", "rm", "unlink"})
            elif action.action_kind == ActionKind.COMMAND_EXEC:
                action_candidates.update({"execute", "exec", "run", "bash", "sh", "cmd"})
            elif action.action_kind == ActionKind.TOOL_CALL:
                action_candidates.update({"call", "invoke", "execute"})

        if action.operation:
            action_candidates.add(action.operation.strip().lower())

        if not (action_candidates & normalized_scope_actions):
            return False

    # 4. Paths dimension
    if scope.paths:
        action_paths = list(action.paths)
        if action.target_path and action.target_path not in action_paths:
            action_paths.append(action.target_path)
        if not action_paths:
            return False

        matched_any_path = False
        for sp in scope.paths:
            if not sp.strip():
                continue
            norm_sp = _normalize_path_str(sp)
            sp_ends_with_slash = sp.strip().replace("\\", "/").endswith("/")
            sp_dir_prefix = norm_sp.rstrip("/") + "/"

            for ap in action_paths:
                norm_ap = _normalize_path_str(ap)

                # Exact match
                if norm_ap == norm_sp or norm_ap.rstrip("/") == norm_sp.rstrip("/"):
                    matched_any_path = True
                    break

                # Directory prefix match
                if sp_ends_with_slash:
                    if norm_ap.startswith(sp_dir_prefix) or norm_ap == norm_sp.rstrip("/"):
                        matched_any_path = True
                        break
                else:
                    if norm_ap.startswith(sp_dir_prefix):
                        matched_any_path = True
                        break

                # Glob match on full normalized path
                if fnmatch.fnmatchcase(norm_ap, norm_sp) or fnmatch.fnmatch(norm_ap.lower(), norm_sp.lower()):
                    matched_any_path = True
                    break

                # Glob match on basename
                basename = norm_ap.split("/")[-1]
                if fnmatch.fnmatchcase(basename, norm_sp) or fnmatch.fnmatch(basename.lower(), norm_sp.lower()):
                    matched_any_path = True
                    break

            if matched_any_path:
                break

        if not matched_any_path:
            return False

    # 5. Selectors dimension (exact typed key-value match)
    if scope.selectors:
        action_dict: dict[str, Any] = dict(action.context)
        if isinstance(action.payload, Mapping):
            action_dict.update({str(k): v for k, v in action.payload.items()})

        for sel_k, sel_v in scope.selectors.items():
            if sel_k not in action_dict:
                return False
            # Truly exact typed comparison: 1 != "1", True != "True", True != 1
            if not _exact_value_equal(action_dict[sel_k], sel_v):
                return False

    return True


class SpecGuard:
    """Deterministic action and observation validation engine.

    Evaluates proposed actions (pre-action) or observed execution results (post-action)
    against active constraints in a ConstraintLedger.
    """

    def __init__(self, ledger: ConstraintLedger | None = None) -> None:
        self._ledger = ledger

    @property
    def ledger(self) -> ConstraintLedger | None:
        """The default ConstraintLedger associated with this guard instance."""
        return self._ledger

    def _resolve_active_constraints(
        self,
        ledger: ConstraintLedger | Iterable[Constraint] | None = None,
    ) -> list[Constraint]:
        """Extract active constraints from the provided ledger, iterable, or instance ledger."""
        target = ledger if ledger is not None else self._ledger
        if target is None:
            return []
        if isinstance(target, ConstraintLedger):
            return list(target.list_active())
        if isinstance(target, Iterable):
            return [c for c in target if c.status == ConstraintStatus.ACTIVE]
        return []

    def evaluate(
        self,
        action: Action,
        ledger: ConstraintLedger | Iterable[Constraint] | None = None,
        trace_pointer: TracePointer | None = None,
    ) -> GuardDecision:
        """Evaluate a proposed action against active constraints (pre-action validation).

        Precedence: BLOCK > WARN > ALLOW.
        Rule semantics:
        - DENY: if applicability scope matches -> violation.
        - REQUIRE: if applicability matches and compliance_scope does NOT match -> violation.
                   if compliance_scope matches -> compliant (no violation).
        - PREFER: if applicability matches and compliance_scope does NOT match -> WARN.
                  if compliance_scope matches -> compliant (no warning).
        - Authority levels:
          - HARD violation -> BLOCK
          - SOFT violation -> WARN
          - ASSUMPTION violation -> WARN (assumptions never independently BLOCK)
        - Unknown/unmatched constraints -> ALLOW
        """
        active_constraints = self._resolve_active_constraints(ledger)
        pointer = trace_pointer or action.trace_pointer

        matched_ids: list[str] = []
        violating_ids: list[str] = []
        reasons: list[str] = []
        highest_decision: DecisionKind = DecisionKind.ALLOW

        for c in active_constraints:
            # 1. Applicability check: does this constraint apply to the action?
            if not match_scope(c.scope, action):
                continue

            matched_ids.append(c.id)
            effect = c.rule_effect

            if effect == RuleEffect.DENY:
                # Prohibited scope matched -> violation
                if c.strength == ConstraintStrength.HARD:
                    violating_ids.append(c.id)
                    reasons.append(
                        f"BLOCK: Action violates HARD constraint '{c.id}' ({c.name}): {c.description}"
                    )
                    highest_decision = DecisionKind.BLOCK
                elif c.strength == ConstraintStrength.SOFT:
                    violating_ids.append(c.id)
                    reasons.append(
                        f"WARN: Action matches SOFT constraint '{c.id}' ({c.name}): {c.description}"
                    )
                    if highest_decision != DecisionKind.BLOCK:
                        highest_decision = DecisionKind.WARN
                elif c.strength == ConstraintStrength.ASSUMPTION:
                    # Invariant: ASSUMPTION must never independently block an action
                    violating_ids.append(c.id)
                    reasons.append(
                        f"WARN: Action conflicts with ASSUMPTION '{c.id}' ({c.name}): {c.description} "
                        f"(assumptions do not independently block)"
                    )
                    if highest_decision != DecisionKind.BLOCK:
                        highest_decision = DecisionKind.WARN

            elif effect == RuleEffect.REQUIRE:
                # REQUIRE: if compliance_scope is not satisfied -> violation.
                # If compliance_scope matches -> compliant, no violation!
                is_compliant = (
                    match_scope(c.compliance_scope, action)
                    if c.compliance_scope is not None
                    else True
                )
                if not is_compliant:
                    violating_ids.append(c.id)
                    if c.strength == ConstraintStrength.HARD:
                        reasons.append(
                            f"BLOCK: Action triggers REQUIRE constraint '{c.id}' ({c.name}) "
                            f"but does not satisfy compliance scope: {c.description}"
                        )
                        highest_decision = DecisionKind.BLOCK
                    else:
                        reasons.append(
                            f"WARN: Action triggers REQUIRE constraint '{c.id}' ({c.name}) "
                            f"but does not satisfy compliance scope: {c.description}"
                        )
                        if highest_decision != DecisionKind.BLOCK:
                            highest_decision = DecisionKind.WARN

            elif effect == RuleEffect.PREFER:
                # PREFER: if preferred/compliance scope is not met -> WARN.
                # If preferred condition matches -> compliant, no warning!
                is_preferred = (
                    match_scope(c.compliance_scope, action)
                    if c.compliance_scope is not None
                    else True
                )
                if not is_preferred:
                    violating_ids.append(c.id)
                    reasons.append(
                        f"WARN: Action triggers PREFER constraint '{c.id}' ({c.name}) "
                        f"but deviates from preferred condition: {c.description}"
                    )
                    if highest_decision != DecisionKind.BLOCK:
                        highest_decision = DecisionKind.WARN

        if not violating_ids:
            reasons.append("Action allowed: no active constraints violated.")

        return GuardDecision(
            decision=highest_decision,
            action=action,
            matched_constraint_ids=_dedup_ordered(matched_ids),
            violating_constraint_ids=_dedup_ordered(violating_ids),
            reasons=_dedup_ordered(reasons),
            trace_pointer=pointer,
        )

    def evaluate_post_action(
        self,
        action: Action,
        observation: ActionObservation,
        ledger: ConstraintLedger | Iterable[Constraint] | None = None,
        trace_pointer: TracePointer | None = None,
    ) -> GuardDecision:
        """Validate all observed runtime effects against active constraints (post-action validation).

        Evaluates:
        1. All changed paths as FILE_WRITE observations.
        2. All accessed paths as FILE_READ observations.
        3. The general action execution effect (tool, action kind, payload).
        Aggregates results deterministically with BLOCK > WARN > ALLOW.
        """
        pointer = trace_pointer or observation.trace_pointer or action.trace_pointer
        effective_context = dict(action.context)
        effective_context.update(dict(observation.context))

        sub_decisions: list[GuardDecision] = []

        # 1. Evaluate changed paths as FILE_WRITE observations
        if observation.changed_paths:
            write_action = Action(
                action_kind=ActionKind.FILE_WRITE,
                tool_name=observation.tool_name or action.tool_name,
                target_type=observation.target_type or action.target_type or "filesystem",
                target_path=observation.changed_paths[0],
                paths=observation.changed_paths,
                operation="write",
                payload=observation.output if observation.output is not None else action.payload,
                context=FrozenDict(effective_context),
                trace_pointer=pointer,
            )
            sub_decisions.append(self.evaluate(write_action, ledger=ledger, trace_pointer=pointer))

        # 2. Evaluate accessed paths as FILE_READ observations
        if observation.accessed_paths:
            read_action = Action(
                action_kind=ActionKind.FILE_READ,
                tool_name=observation.tool_name or action.tool_name,
                target_type=observation.target_type or action.target_type or "filesystem",
                target_path=observation.accessed_paths[0],
                paths=observation.accessed_paths,
                operation="read",
                payload=observation.output if observation.output is not None else action.payload,
                context=FrozenDict(effective_context),
                trace_pointer=pointer,
            )
            sub_decisions.append(self.evaluate(read_action, ledger=ledger, trace_pointer=pointer))

        # 3. Evaluate general tool execution / action kind effect
        general_paths = observation.changed_paths + observation.accessed_paths
        if not general_paths:
            general_paths = action.paths

        general_action = Action(
            action_kind=observation.action_kind or action.action_kind,
            tool_name=observation.tool_name or action.tool_name,
            target_type=observation.target_type or action.target_type,
            target_path=general_paths[0] if general_paths else action.target_path,
            paths=general_paths,
            operation=action.operation,
            payload=observation.output if observation.output is not None else action.payload,
            context=FrozenDict(effective_context),
            trace_pointer=pointer,
        )
        sub_decisions.append(self.evaluate(general_action, ledger=ledger, trace_pointer=pointer))

        # Deterministically aggregate all sub-decisions
        return self._aggregate_decisions(
            action=general_action,
            decisions=sub_decisions,
            trace_pointer=pointer,
        )

    def _aggregate_decisions(
        self,
        action: Action,
        decisions: list[GuardDecision],
        trace_pointer: TracePointer | None = None,
    ) -> GuardDecision:
        """Deterministically aggregate multiple decisions with BLOCK > WARN > ALLOW precedence."""
        highest_decision = DecisionKind.ALLOW
        all_matched: list[str] = []
        all_violating: list[str] = []
        all_reasons: list[str] = []

        for d in decisions:
            if d.decision == DecisionKind.BLOCK:
                highest_decision = DecisionKind.BLOCK
            elif d.decision == DecisionKind.WARN and highest_decision != DecisionKind.BLOCK:
                highest_decision = DecisionKind.WARN

            all_matched.extend(d.matched_constraint_ids)
            all_violating.extend(d.violating_constraint_ids)
            all_reasons.extend(d.reasons)

        dedup_matched = _dedup_ordered(all_matched)
        dedup_violating = _dedup_ordered(all_violating)

        if dedup_violating:
            filtered_reasons = [r for r in all_reasons if not r.startswith("Action allowed:")]
        else:
            filtered_reasons = all_reasons or ["Action allowed: no active constraints violated."]
        dedup_reasons = _dedup_ordered(filtered_reasons)

        return GuardDecision(
            decision=highest_decision,
            action=action,
            matched_constraint_ids=dedup_matched,
            violating_constraint_ids=dedup_violating,
            reasons=dedup_reasons,
            trace_pointer=trace_pointer,
        )

    def evaluate_observation(
        self,
        observation: ActionObservation,
        ledger: ConstraintLedger | Iterable[Constraint] | None = None,
        action: Action | None = None,
        trace_pointer: TracePointer | None = None,
    ) -> GuardDecision:
        """Convenience method to evaluate an ActionObservation with or without prior Action."""
        effective_action = action or Action(
            action_kind=observation.action_kind or ActionKind.GENERIC,
            tool_name=observation.tool_name,
            target_type=observation.target_type,
            payload=observation.output,
            context=observation.context,
            trace_pointer=observation.trace_pointer,
        )
        return self.evaluate_post_action(
            action=effective_action,
            observation=observation,
            ledger=ledger,
            trace_pointer=trace_pointer,
        )
