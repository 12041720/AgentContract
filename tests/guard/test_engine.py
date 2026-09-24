"""Tests for SpecGuard execution engine, matching rules, and required scenarios."""

import pytest

from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStatus,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.guard.engine import SpecGuard, match_scope
from agentcontract.guard.models import (
    Action,
    ActionKind,
    ActionObservation,
    DecisionKind,
    GuardDecision,
)
from agentcontract.trace.models import TracePointer


@pytest.fixture
def empty_ledger() -> ConstraintLedger:
    return ConstraintLedger()


def _make_constraint(
    cid: str,
    name: str = "test_rule",
    strength: ConstraintStrength = ConstraintStrength.HARD,
    status: ConstraintStatus = ConstraintStatus.ACTIVE,
    rule_effect: RuleEffect = RuleEffect.DENY,
    scope: ConstraintScope | None = None,
    source: ConstraintSource = ConstraintSource.USER,
) -> Constraint:
    return Constraint(
        id=cid,
        name=name,
        description=f"Rule description for {cid}",
        strength=strength,
        status=status,
        rule_effect=rule_effect,
        provenance=ConstraintProvenance(source=source),
        scope=scope or ConstraintScope(),
    )


# --- Scenario 1: Hard path prohibition blocks write ---

def test_scenario_1_hard_path_prohibition_blocks_write(empty_ledger: ConstraintLedger):
    """Scenario 1: A hard constraint prohibiting writes to a path causes BLOCK."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-no-state-edit",
            name="protect_state",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                paths=[".agent/STATE.md"],
                actions=["write"],
            ),
        )
    )

    guard = SpecGuard(ledger=ledger)
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path=".agent/STATE.md",
    )

    decision = guard.evaluate(action)
    assert decision.decision == DecisionKind.BLOCK
    assert decision.is_blocked is True
    assert "c-no-state-edit" in decision.matched_constraint_ids
    assert "c-no-state-edit" in decision.violating_constraint_ids
    assert "BLOCK: Action violates HARD constraint" in decision.reason


# --- Scenario 2: Soft path preference warns ---

def test_scenario_2_soft_path_preference_warns(empty_ledger: ConstraintLedger):
    """Scenario 2: A soft constraint produces WARN without blocking."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-legacy-warn",
            name="discourage_legacy",
            strength=ConstraintStrength.SOFT,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                paths=["src/legacy/"],
                actions=["write"],
            ),
        )
    )

    guard = SpecGuard(ledger=ledger)
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        paths=["src/legacy/parser.py"],
    )

    decision = guard.evaluate(action)
    assert decision.decision == DecisionKind.WARN
    assert decision.is_warned is True
    assert decision.is_blocked is False
    assert "c-legacy-warn" in decision.matched_constraint_ids
    assert "c-legacy-warn" in decision.violating_constraint_ids
    assert "WARN: Action matches SOFT constraint" in decision.reason


# --- Scenario 3: Assumption alone does not block ---

def test_scenario_3_assumption_alone_does_not_block(empty_ledger: ConstraintLedger):
    """Scenario 3: An ASSUMPTION constraint must NEVER independently block an action."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-assume-sqlite",
            name="assume_sqlite_only",
            strength=ConstraintStrength.ASSUMPTION,
            rule_effect=RuleEffect.DENY,
            source=ConstraintSource.AGENT_INFERENCE,
            scope=ConstraintScope(
                paths=["config/database.yml"],
                actions=["write"],
            ),
        )
    )

    guard = SpecGuard(ledger=ledger)
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="config/database.yml",
    )

    decision = guard.evaluate(action)
    # Must produce WARN, never BLOCK
    assert decision.decision == DecisionKind.WARN
    assert decision.is_warned is True
    assert decision.is_blocked is False
    assert "c-assume-sqlite" in decision.violating_constraint_ids
    assert "assumptions do not independently block" in decision.reason

    # Even multiple matching assumptions never produce BLOCK
    ledger.add(
        _make_constraint(
            cid="c-assume-port",
            name="assume_port_8080",
            strength=ConstraintStrength.ASSUMPTION,
            rule_effect=RuleEffect.DENY,
            source=ConstraintSource.AGENT_INFERENCE,
            scope=ConstraintScope(
                paths=["config/database.yml"],
            ),
        )
    )
    multi_decision = guard.evaluate(action)
    assert multi_decision.decision == DecisionKind.WARN
    assert multi_decision.is_blocked is False


# --- Scenario 4: Unrelated constraint -> allow ---

def test_scenario_4_unrelated_constraint_allows_action(empty_ledger: ConstraintLedger):
    """Scenario 4: An active constraint with unrelated scope does not block or warn."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-no-prod-db",
            name="protect_prod_db",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                target_type="database",
                paths=["migrations/"],
                tools=["db_client"],
            ),
        )
    )

    guard = SpecGuard(ledger=ledger)
    # Action touches filesystem, different path and tool
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_type="filesystem",
        target_path="src/utils.py",
        tool_name="code_editor",
    )

    decision = guard.evaluate(action)
    assert decision.decision == DecisionKind.ALLOW
    assert decision.is_allowed is True
    assert len(decision.matched_constraint_ids) == 0
    assert len(decision.violating_constraint_ids) == 0


# --- Scenario 5: Multiple constraints where BLOCK dominates WARN ---

def test_scenario_5_multiple_constraints_block_dominates_warn(empty_ledger: ConstraintLedger):
    """Scenario 5: Precedence: BLOCK dominates WARN; WARN dominates ALLOW."""
    ledger = empty_ledger

    # Soft constraint (produces WARN)
    ledger.add(
        _make_constraint(
            cid="c-soft-src",
            name="src_audit",
            strength=ConstraintStrength.SOFT,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(paths=["src/"]),
        )
    )

    # Assumption constraint (produces WARN)
    ledger.add(
        _make_constraint(
            cid="c-assump-auth",
            name="assume_auth",
            strength=ConstraintStrength.ASSUMPTION,
            rule_effect=RuleEffect.DENY,
            source=ConstraintSource.AGENT_INFERENCE,
            scope=ConstraintScope(paths=["src/auth/"]),
        )
    )

    # Hard constraint (produces BLOCK)
    ledger.add(
        _make_constraint(
            cid="c-hard-keys",
            name="no_key_edits",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(paths=["src/auth/keys.py"]),
        )
    )

    guard = SpecGuard(ledger=ledger)
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="src/auth/keys.py",
    )

    decision = guard.evaluate(action)
    # All 3 matched, but HARD constraint causes final decision to be BLOCK
    assert decision.decision == DecisionKind.BLOCK
    assert decision.is_blocked is True
    assert set(decision.matched_constraint_ids) == {"c-soft-src", "c-assump-auth", "c-hard-keys"}
    assert set(decision.violating_constraint_ids) == {"c-soft-src", "c-assump-auth", "c-hard-keys"}

    # Test WARN dominates ALLOW when BLOCK constraint does not match
    safe_action = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="src/components/button.py",
    )
    safe_decision = guard.evaluate(safe_action)
    # Only c-soft-src matches -> WARN dominates ALLOW
    assert safe_decision.decision == DecisionKind.WARN
    assert safe_decision.is_warned is True
    assert safe_decision.matched_constraint_ids == ("c-soft-src",)


# --- Scenario 6: Non-ACTIVE constraints are not enforced ---

def test_scenario_6_non_active_constraints_not_enforced(empty_ledger: ConstraintLedger):
    """Scenario 6: REVOKED, SUPERSEDED, and CONFLICTED constraints do not participate in active enforcement."""
    ledger = empty_ledger

    # Add constraints in non-active states
    c_revoked = _make_constraint(
        cid="c-revoked",
        status=ConstraintStatus.REVOKED,
        strength=ConstraintStrength.HARD,
        scope=ConstraintScope(paths=["secret.txt"]),
    )
    c_superseded = _make_constraint(
        cid="c-superseded",
        status=ConstraintStatus.SUPERSEDED,
        strength=ConstraintStrength.HARD,
        scope=ConstraintScope(paths=["secret.txt"]),
    )
    c_conflicted = _make_constraint(
        cid="c-conflicted",
        status=ConstraintStatus.CONFLICTED,
        strength=ConstraintStrength.HARD,
        scope=ConstraintScope(paths=["secret.txt"]),
    )

    guard = SpecGuard(ledger=ledger)
    action = Action(action_kind=ActionKind.FILE_WRITE, target_path="secret.txt")

    # Evaluate passing explicit iterable with non-active constraints
    decision = guard.evaluate(action, ledger=[c_revoked, c_superseded, c_conflicted])
    assert decision.decision == DecisionKind.ALLOW
    assert decision.is_allowed is True
    assert len(decision.matched_constraint_ids) == 0


# --- Scenario 7: Tool-name matching ---

def test_scenario_7_tool_name_matching(empty_ledger: ConstraintLedger):
    """Scenario 7: Tool matching is exact and normalized case-insensitively."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-no-bash",
            name="prohibit_bash",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(tools=["bash", "terminal"]),
        )
    )

    guard = SpecGuard(ledger=ledger)

    # Tool matches -> BLOCKED
    a_bash = Action(action_kind=ActionKind.COMMAND_EXEC, tool_name="bash")
    assert guard.evaluate(a_bash).is_blocked is True

    # Case variance matches -> BLOCKED
    a_case = Action(action_kind=ActionKind.COMMAND_EXEC, tool_name="BASH")
    assert guard.evaluate(a_case).is_blocked is True

    # Other tool does not match -> ALLOWED
    a_safe = Action(action_kind=ActionKind.TOOL_CALL, tool_name="python_runner")
    assert guard.evaluate(a_safe).is_allowed is True


# --- Scenario 8: Action-kind matching ---

def test_scenario_8_action_kind_matching(empty_ledger: ConstraintLedger):
    """Scenario 8: Action-kind and operation verbs match populated action scope."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-no-delete",
            name="prohibit_delete",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(actions=["delete", "drop_table"]),
        )
    )

    guard = SpecGuard(ledger=ledger)

    # ActionKind.FILE_DELETE maps to delete -> BLOCKED
    a_del = Action(action_kind=ActionKind.FILE_DELETE, target_path="data.db")
    assert guard.evaluate(a_del).is_blocked is True

    # Specific operation verb matches -> BLOCKED
    a_op = Action(action_kind=ActionKind.GENERIC, operation="drop_table")
    assert guard.evaluate(a_op).is_blocked is True

    # Non-matching action -> ALLOWED
    a_read = Action(action_kind=ActionKind.FILE_READ, target_path="data.db")
    assert guard.evaluate(a_read).is_allowed is True


# --- Scenario 9: Target-type matching ---

def test_scenario_9_target_type_matching(empty_ledger: ConstraintLedger):
    """Scenario 9: target_type must match when populated in constraint scope."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-db-only",
            name="database_policy",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(target_type="database"),
        )
    )

    guard = SpecGuard(ledger=ledger)

    # Matching target_type -> BLOCKED
    a_db = Action(action_kind=ActionKind.GENERIC, target_type="database")
    assert guard.evaluate(a_db).is_blocked is True

    # Different target_type -> ALLOWED
    a_fs = Action(action_kind=ActionKind.GENERIC, target_type="filesystem")
    assert guard.evaluate(a_fs).is_allowed is True

    # None target_type -> ALLOWED
    a_none = Action(action_kind=ActionKind.GENERIC, target_type=None)
    assert guard.evaluate(a_none).is_allowed is True


# --- Scenario 10: Selector exact-match behavior ---

def test_scenario_10_selector_exact_match_behavior(empty_ledger: ConstraintLedger):
    """Scenario 10: Selectors require exact key-value matching in action context or payload."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-prod-selector",
            name="prod_gate",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(
                selectors={"environment": "production", "tier": "p0"},
            ),
        )
    )

    guard = SpecGuard(ledger=ledger)

    # Exactly matching selectors -> BLOCKED
    a_match = Action(
        action_kind=ActionKind.STATE_CHANGE,
        context={"environment": "production", "tier": "p0", "other": "ignored"},
    )
    assert guard.evaluate(a_match).is_blocked is True

    # One selector value differs -> ALLOWED
    a_diff_val = Action(
        action_kind=ActionKind.STATE_CHANGE,
        context={"environment": "staging", "tier": "p0"},
    )
    assert guard.evaluate(a_diff_val).is_allowed is True

    # Missing a required selector key -> ALLOWED
    a_missing_key = Action(
        action_kind=ActionKind.STATE_CHANGE,
        context={"environment": "production"},
    )
    assert guard.evaluate(a_missing_key).is_allowed is True


# --- Scenario 11: Decision contains matched constraint IDs ---

def test_scenario_11_decision_contains_matched_constraint_ids(empty_ledger: ConstraintLedger):
    """Scenario 11: Non-ALLOW decision explicitly identifies the triggering constraint IDs and reasons."""
    ledger = empty_ledger
    c1 = _make_constraint(
        cid="c-rule-alpha",
        name="rule_alpha",
        strength=ConstraintStrength.HARD,
        scope=ConstraintScope(paths=["main.py"]),
    )
    c2 = _make_constraint(
        cid="c-rule-beta",
        name="rule_beta",
        strength=ConstraintStrength.SOFT,
        scope=ConstraintScope(paths=["main.py"]),
    )
    ledger.add(c1)
    ledger.add(c2)

    guard = SpecGuard(ledger=ledger)
    action = Action(action_kind=ActionKind.FILE_WRITE, target_path="main.py")

    decision = guard.evaluate(action)
    assert "c-rule-alpha" in decision.matched_constraint_ids
    assert "c-rule-beta" in decision.matched_constraint_ids
    assert "c-rule-alpha" in decision.violating_constraint_ids
    assert "c-rule-beta" in decision.violating_constraint_ids
    assert any("c-rule-alpha" in r for r in decision.reasons)
    assert any("c-rule-beta" in r for r in decision.reasons)


# --- Scenario 12: Action / Decision serialization round-trip ---

def test_scenario_12_serialization_round_trip():
    """Scenario 12: Complete Action and GuardDecision state survives JSON serialization round-trip."""
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="schema.sql",
        paths=["schema.sql", "migrations/001.sql"],
        tool_name="file_writer",
        operation="write",
        payload={"content": "CREATE TABLE users;"},
        context={"git_branch": "feature/db"},
        trace_pointer=TracePointer(trace_id="tr-test", event_id="evt-1"),
    )
    decision = GuardDecision(
        decision=DecisionKind.BLOCK,
        action=action,
        matched_constraint_ids=["c-no-ddl"],
        violating_constraint_ids=["c-no-ddl"],
        reasons=["BLOCK: DDL operations forbidden."],
        trace_pointer=action.trace_pointer,
    )

    json_str = decision.model_dump_json()
    rebuilt = GuardDecision.model_validate_json(json_str)

    assert rebuilt == decision
    assert rebuilt.action == action
    assert rebuilt.is_blocked is True
    assert rebuilt.trace_pointer == action.trace_pointer


# --- Scenario 13: TracePointer retained in decision ---

def test_scenario_13_trace_pointer_retained_in_decision(empty_ledger: ConstraintLedger):
    """Scenario 13: TracePointer provenance is faithfully retained in GuardDecision."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-warn-tool",
            name="warn_tool",
            strength=ConstraintStrength.SOFT,
            scope=ConstraintScope(tools=["curl"]),
        )
    )

    ptr = TracePointer(trace_id="tr-provenance", event_id="evt-curl-call", session_id="sess-99")
    action = Action(
        action_kind=ActionKind.TOOL_CALL,
        tool_name="curl",
        trace_pointer=ptr,
    )

    guard = SpecGuard(ledger=ledger)
    decision = guard.evaluate(action)
    assert decision.trace_pointer == ptr
    assert decision.trace_pointer.trace_id == "tr-provenance"
    assert decision.trace_pointer.event_id == "evt-curl-call"
    assert decision.trace_pointer.session_id == "sess-99"

    # Passing explicit trace_pointer to evaluate() overrides or supplies it
    override_ptr = TracePointer(trace_id="tr-override", event_id="evt-override")
    decision2 = guard.evaluate(action, trace_pointer=override_ptr)
    assert decision2.trace_pointer == override_ptr


# --- Scenario 14: Post-action observation detects a hard violation ---

def test_scenario_14_post_action_observation_detects_hard_violation(empty_ledger: ConstraintLedger):
    """Scenario 14: Post-action observation detects an unauthorized file write that was not declared in pre-action."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-no-etc-hosts",
            name="protect_hosts",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(paths=["/etc/hosts", "etc/hosts"]),
        )
    )

    guard = SpecGuard(ledger=ledger)

    # Pre-action declared a safe scratch path -> ALLOWED
    action = Action(
        action_kind=ActionKind.COMMAND_EXEC,
        tool_name="bash",
        target_path="tmp/script.sh",
        paths=["tmp/script.sh"],
    )
    pre_decision = guard.evaluate(action)
    assert pre_decision.is_allowed is True

    # Post-action execution actually wrote to /etc/hosts -> BLOCKED
    observation = ActionObservation(
        tool_name="bash",
        changed_paths=["/etc/hosts"],
        exit_code=0,
    )
    post_decision = guard.evaluate_post_action(action, observation)
    assert post_decision.decision == DecisionKind.BLOCK
    assert post_decision.is_blocked is True
    assert "c-no-etc-hosts" in post_decision.violating_constraint_ids

    # evaluate_observation directly also detects it
    obs_direct = guard.evaluate_observation(observation)
    assert obs_direct.is_blocked is True
    assert "c-no-etc-hosts" in obs_direct.violating_constraint_ids


# --- Additional Scenario: RuleEffect.PREFER and RuleEffect.REQUIRE ---

def test_rule_effect_prefer_and_require_semantics(empty_ledger: ConstraintLedger):
    """Verify RuleEffect.PREFER produces WARN and RuleEffect.REQUIRE produces BLOCK when triggered."""
    ledger = empty_ledger

    # PREFER constraint produces WARN even when declared with HARD strength
    ledger.add(
        _make_constraint(
            cid="c-prefer-type",
            name="prefer_pydantic",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.PREFER,
            scope=ConstraintScope(paths=["models.py"]),
        )
    )

    # REQUIRE constraint produces BLOCK when triggered
    ledger.add(
        _make_constraint(
            cid="c-require-audit",
            name="require_audit",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.REQUIRE,
            scope=ConstraintScope(tools=["rm"]),
        )
    )

    guard = SpecGuard(ledger=ledger)

    # Action matches PREFER -> WARN
    a_pref = Action(action_kind=ActionKind.FILE_WRITE, target_path="models.py")
    d_pref = guard.evaluate(a_pref)
    assert d_pref.decision == DecisionKind.WARN
    assert "c-prefer-type" in d_pref.violating_constraint_ids
    assert "PREFER" in d_pref.reason

    # Action matches REQUIRE -> BLOCK
    a_req = Action(action_kind=ActionKind.COMMAND_EXEC, tool_name="rm")
    d_req = guard.evaluate(a_req)
    assert d_req.decision == DecisionKind.BLOCK
    assert "c-require-audit" in d_req.violating_constraint_ids
    assert "REQUIRE" in d_req.reason
