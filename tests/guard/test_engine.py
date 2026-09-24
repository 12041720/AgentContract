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
    compliance_scope: ConstraintScope | None = None,
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
        compliance_scope=compliance_scope,
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

    # BLOCKER 2: Typed mismatches (1 != "1", True != "True", True != 1) must NOT match
    ledger_typed = ConstraintLedger()
    ledger_typed.add(
        _make_constraint(
            cid="c-typed-port",
            name="typed_int_port",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(selectors={"port": 8080, "active": True}),
        )
    )
    guard_typed = SpecGuard(ledger=ledger_typed)

    # Exact typed match (int 8080, bool True) -> BLOCKED
    a_exact_typed = Action(
        action_kind=ActionKind.GENERIC,
        context={"port": 8080, "active": True},
    )
    assert guard_typed.evaluate(a_exact_typed).is_blocked is True

    # String "8080" instead of int 8080 -> NOT a match -> ALLOWED
    a_str_port = Action(
        action_kind=ActionKind.GENERIC,
        context={"port": "8080", "active": True},
    )
    assert guard_typed.evaluate(a_str_port).is_allowed is True

    # String "True" instead of bool True -> NOT a match -> ALLOWED
    a_str_bool = Action(
        action_kind=ActionKind.GENERIC,
        context={"port": 8080, "active": "True"},
    )
    assert guard_typed.evaluate(a_str_bool).is_allowed is True

    # Int 1 instead of bool True -> NOT a match -> ALLOWED
    a_int_bool = Action(
        action_kind=ActionKind.GENERIC,
        context={"port": 8080, "active": 1},
    )
    assert guard_typed.evaluate(a_int_bool).is_allowed is True

    # BLOCKER 1 (ROUND 2): Scalar int-vs-float (1 != 1.0) must NOT match
    ledger_numeric = ConstraintLedger()
    ledger_numeric.add(
        _make_constraint(
            cid="c-int-retries",
            name="int_retries_gate",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(selectors={"retries": 1}),
        )
    )
    ledger_numeric.add(
        _make_constraint(
            cid="c-float-ratio",
            name="float_ratio_gate",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(selectors={"ratio": 1.0}),
        )
    )
    guard_numeric = SpecGuard(ledger=ledger_numeric)

    # Float 1.0 instead of int 1 -> NOT a match for c-int-retries
    a_float_for_int = Action(action_kind=ActionKind.GENERIC, context={"retries": 1.0})
    assert guard_numeric.evaluate(a_float_for_int).is_allowed is True

    # Int 1 matches int 1 -> BLOCKED
    a_int_for_int = Action(action_kind=ActionKind.GENERIC, context={"retries": 1})
    d_int_for_int = guard_numeric.evaluate(a_int_for_int)
    assert d_int_for_int.is_blocked is True
    assert "c-int-retries" in d_int_for_int.violating_constraint_ids

    # Int 1 instead of float 1.0 -> NOT a match for c-float-ratio
    a_int_for_float = Action(action_kind=ActionKind.GENERIC, context={"ratio": 1})
    assert guard_numeric.evaluate(a_int_for_float).is_allowed is True

    # Float 1.0 matches float 1.0 -> BLOCKED
    a_float_for_float = Action(action_kind=ActionKind.GENERIC, context={"ratio": 1.0})
    d_float_for_float = guard_numeric.evaluate(a_float_for_float)
    assert d_float_for_float.is_blocked is True
    assert "c-float-ratio" in d_float_for_float.violating_constraint_ids

    # BLOCKER 1 (ROUND 2): Nested mapping and sequence typed mismatches
    ledger_nested = ConstraintLedger()
    ledger_nested.add(
        _make_constraint(
            cid="c-nested-dict",
            name="nested_dict_gate",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(selectors={"config": {"retries": 1}}),
        )
    )
    ledger_nested.add(
        _make_constraint(
            cid="c-nested-seq",
            name="nested_seq_gate",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(selectors={"levels": (1, 2)}),
        )
    )
    guard_nested = SpecGuard(ledger=ledger_nested)

    # Nested dict with float 1.0 instead of int 1 -> NOT a match -> ALLOWED
    a_nested_dict_float = Action(
        action_kind=ActionKind.GENERIC,
        context={"config": {"retries": 1.0}},
    )
    assert guard_nested.evaluate(a_nested_dict_float).is_allowed is True

    # Nested dict with exact int 1 -> BLOCKED
    a_nested_dict_exact = Action(
        action_kind=ActionKind.GENERIC,
        context={"config": {"retries": 1}},
    )
    d_nested_dict = guard_nested.evaluate(a_nested_dict_exact)
    assert d_nested_dict.is_blocked is True
    assert "c-nested-dict" in d_nested_dict.violating_constraint_ids

    # Nested sequence with float 2.0 instead of int 2 -> NOT a match -> ALLOWED
    a_nested_seq_float = Action(
        action_kind=ActionKind.GENERIC,
        context={"levels": (1, 2.0)},
    )
    assert guard_nested.evaluate(a_nested_seq_float).is_allowed is True

    # Nested sequence with exact ints -> BLOCKED
    a_nested_seq_exact = Action(
        action_kind=ActionKind.GENERIC,
        context={"levels": (1, 2)},
    )
    d_nested_seq = guard_nested.evaluate(a_nested_seq_exact)
    assert d_nested_seq.is_blocked is True
    assert "c-nested-seq" in d_nested_seq.violating_constraint_ids


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
    """Scenario 14: Post-action observation detects unauthorized effects across both writes and reads."""
    ledger = empty_ledger
    ledger.add(
        _make_constraint(
            cid="c-no-etc-hosts",
            name="protect_hosts",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(paths=["/etc/hosts", "etc/hosts"], actions=["write"]),
        )
    )
    ledger.add(
        _make_constraint(
            cid="c-no-shadow-read",
            name="protect_shadow_read",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.DENY,
            scope=ConstraintScope(paths=["/etc/shadow", "etc/shadow"], actions=["read"]),
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

    # Post-action execution wrote to /etc/hosts -> BLOCKED
    observation = ActionObservation(
        tool_name="bash",
        changed_paths=["/etc/hosts"],
        exit_code=0,
    )
    post_decision = guard.evaluate_post_action(action, observation)
    assert post_decision.decision == DecisionKind.BLOCK
    assert post_decision.is_blocked is True
    assert "c-no-etc-hosts" in post_decision.violating_constraint_ids

    # BLOCKER 3: Safe write and forbidden read in the same observation -> read violation MUST be detected
    mixed_obs = ActionObservation(
        tool_name="bash",
        changed_paths=["tmp/safe_out.txt"],   # Safe write
        accessed_paths=["/etc/shadow"],       # Forbidden read!
        exit_code=0,
    )
    mixed_decision = guard.evaluate_post_action(action, mixed_obs)
    assert mixed_decision.decision == DecisionKind.BLOCK
    assert mixed_decision.is_blocked is True
    assert "c-no-shadow-read" in mixed_decision.violating_constraint_ids
    assert "BLOCK" in mixed_decision.reason

    # evaluate_observation directly also detects it
    obs_direct = guard.evaluate_observation(mixed_obs)
    assert obs_direct.is_blocked is True
    assert "c-no-shadow-read" in obs_direct.violating_constraint_ids


# --- Additional Scenario: RuleEffect.PREFER and RuleEffect.REQUIRE ---

def test_rule_effect_prefer_and_require_semantics(empty_ledger: ConstraintLedger):
    """Verify RuleEffect.REQUIRE and RuleEffect.PREFER compliance vs applicability semantics."""
    ledger = empty_ledger

    # REQUIRE rule: file writes REQUIRE paths to be within sandbox/
    ledger.add(
        _make_constraint(
            cid="c-require-sandbox",
            name="require_sandbox_writes",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.REQUIRE,
            scope=ConstraintScope(actions=["write"]),
            compliance_scope=ConstraintScope(paths=["sandbox/"]),
        )
    )

    # PREFER rule: actions on sandbox/src/ PREFER using black_formatter
    ledger.add(
        _make_constraint(
            cid="c-prefer-black",
            name="prefer_black_formatting",
            strength=ConstraintStrength.HARD,
            rule_effect=RuleEffect.PREFER,
            scope=ConstraintScope(paths=["sandbox/src/"]),
            compliance_scope=ConstraintScope(tools=["black_formatter"]),
        )
    )

    guard = SpecGuard(ledger=ledger)

    # REQUIRE Case 1: Write within sandbox/ satisfies compliance -> ALLOWED
    a_req_ok = Action(action_kind=ActionKind.FILE_WRITE, target_path="sandbox/main.py")
    d_req_ok = guard.evaluate(a_req_ok)
    assert d_req_ok.decision == DecisionKind.ALLOW
    assert d_req_ok.is_allowed is True
    assert "c-require-sandbox" in d_req_ok.matched_constraint_ids
    assert len(d_req_ok.violating_constraint_ids) == 0

    # REQUIRE Case 2: Write outside sandbox/ violates compliance -> BLOCKED
    a_req_bad = Action(action_kind=ActionKind.FILE_WRITE, target_path="src/sensitive.py")
    d_req_bad = guard.evaluate(a_req_bad)
    assert d_req_bad.decision == DecisionKind.BLOCK
    assert d_req_bad.is_blocked is True
    assert "c-require-sandbox" in d_req_bad.violating_constraint_ids
    assert "does not satisfy compliance scope" in d_req_bad.reason

    # REQUIRE Case 3: Read outside sandbox/ does not trigger write applicability -> ALLOWED
    a_req_read = Action(action_kind=ActionKind.FILE_READ, target_path="src/sensitive.py")
    d_req_read = guard.evaluate(a_req_read)
    # Does not match applicability scope
    assert "c-require-sandbox" not in d_req_read.matched_constraint_ids

    # PREFER Case 1: Action on src/ uses black_formatter -> preferred condition met -> ALLOWED (no warning)
    a_pref_ok = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="sandbox/src/file.py",
        paths=["sandbox/src/file.py"],
        tool_name="black_formatter",
    )
    d_pref_ok = guard.evaluate(a_pref_ok)
    # Should not warn for c-prefer-black
    assert "c-prefer-black" not in d_pref_ok.violating_constraint_ids

    # PREFER Case 2: Action on src/ uses other tool -> preferred condition not met -> WARN
    a_pref_warn = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="sandbox/src/file.py",
        paths=["sandbox/src/file.py"],
        tool_name="nano",
    )
    d_pref_warn = guard.evaluate(a_pref_warn)
    assert d_pref_warn.decision == DecisionKind.WARN
    assert "c-prefer-black" in d_pref_warn.violating_constraint_ids
    assert "deviates from preferred condition" in d_pref_warn.reason

    # PREFER Case 3: Action outside src/ does not trigger preference rule -> ALLOWED
    a_pref_other = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="sandbox/docs/readme.md",
        paths=["sandbox/docs/readme.md"],
        tool_name="nano",
    )
    d_pref_other = guard.evaluate(a_pref_other)
    assert "c-prefer-black" not in d_pref_other.matched_constraint_ids

