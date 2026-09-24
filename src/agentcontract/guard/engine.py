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


def match_scope(scope: ConstraintScope, action: Action) -> bool:
    """Deterministically check if an action matches all populated dimensions of a constraint scope.

    Matching rules:
    - Empty scope field means 'no restriction on that dimension' (matches everything).
    - Populated target_type must match action.target_type (case-insensitive).
    - Populated tools must contain action.tool_name (case-insensitive).
    - Populated actions must contain action.action_kind or action.operation.
    - Populated paths must match at least one path in action.paths (exact, directory prefix, or glob).
    - Populated selectors must match exact key/value pairs in action.context or action.payload.
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

    # 5. Selectors dimension (exact key-value match)
    if scope.selectors:
        action_dict: dict[str, Any] = dict(action.context)
        if isinstance(action.payload, Mapping):
            action_dict.update({str(k): v for k, v in action.payload.items()})

        for sel_k, sel_v in scope.selectors.items():
            if sel_k not in action_dict:
                return False
            if str(action_dict[sel_k]).strip() != str(sel_v).strip():
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
        - HARD constraint violation -> BLOCK
        - SOFT constraint violation -> WARN
        - ASSUMPTION violation -> WARN (assumptions never independently BLOCK)
        - PREFER rule effect -> WARN
        - Unknown/unmatched constraints -> ALLOW
        """
        active_constraints = self._resolve_active_constraints(ledger)
        pointer = trace_pointer or action.trace_pointer

        matched_ids: list[str] = []
        violating_ids: list[str] = []
        reasons: list[str] = []
        highest_decision: DecisionKind = DecisionKind.ALLOW

        for c in active_constraints:
            if not match_scope(c.scope, action):
                continue

            matched_ids.append(c.id)
            effect = c.effective_rule_effect

            if effect == RuleEffect.DENY:
                # Prohibited action matched
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

            elif effect == RuleEffect.PREFER:
                # Advisory preference deviation
                violating_ids.append(c.id)
                reasons.append(
                    f"WARN: Action deviates from PREFER constraint '{c.id}' ({c.name}): {c.description}"
                )
                if highest_decision != DecisionKind.BLOCK:
                    highest_decision = DecisionKind.WARN

            elif effect == RuleEffect.REQUIRE:
                # Requirement rule: matching scope defines the domain where compliance is required
                violating_ids.append(c.id)
                if c.strength == ConstraintStrength.HARD:
                    reasons.append(
                        f"BLOCK: Action triggers REQUIRE constraint '{c.id}' ({c.name}): {c.description}"
                    )
                    highest_decision = DecisionKind.BLOCK
                else:
                    reasons.append(
                        f"WARN: Action triggers REQUIRE constraint '{c.id}' ({c.name}): {c.description}"
                    )
                    if highest_decision != DecisionKind.BLOCK:
                        highest_decision = DecisionKind.WARN

        if not violating_ids:
            reasons.append("Action allowed: no active constraints violated.")

        return GuardDecision(
            decision=highest_decision,
            action=action,
            matched_constraint_ids=tuple(matched_ids),
            violating_constraint_ids=tuple(violating_ids),
            reasons=tuple(reasons),
            trace_pointer=pointer,
        )

    def evaluate_post_action(
        self,
        action: Action,
        observation: ActionObservation,
        ledger: ConstraintLedger | Iterable[Constraint] | None = None,
        trace_pointer: TracePointer | None = None,
    ) -> GuardDecision:
        """Validate observed runtime effects against active constraints (post-action validation).

        Synthesizes an observed action using actual executed paths, tool, and outcome,
        detecting any post-execution constraint violations (e.g. unexpected path writes).
        """
        pointer = trace_pointer or observation.trace_pointer or action.trace_pointer

        # Determine effective observed paths
        observed_paths = observation.changed_paths or observation.accessed_paths or action.paths

        # Determine effective context
        effective_context = dict(action.context)
        effective_context.update(dict(observation.context))

        observed_action = Action(
            action_kind=observation.action_kind or action.action_kind,
            tool_name=observation.tool_name or action.tool_name,
            target_type=observation.target_type or action.target_type,
            target_path=observed_paths[0] if observed_paths else action.target_path,
            paths=observed_paths,
            operation=action.operation,
            payload=observation.output if observation.output is not None else action.payload,
            context=FrozenDict(effective_context),
            trace_pointer=pointer,
        )

        return self.evaluate(observed_action, ledger=ledger, trace_pointer=pointer)

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
            paths=observation.changed_paths or observation.accessed_paths,
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
