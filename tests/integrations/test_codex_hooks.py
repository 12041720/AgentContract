"""Integration tests for Codex lifecycle hook executions and SpecGuard/EvidenceGate gating."""

import json
from pathlib import Path
from typing import Any
import pytest

from agentcontract.constraints.models import ConstraintStatus
from agentcontract.integrations.codex.adapter import CodexHookAdapter
from agentcontract.integrations.codex.hooks import (
    handle_post_tool_use,
    handle_pre_tool_use,
    handle_session_start,
    handle_stop,
    handle_user_prompt_submit,
    run_hook,
)
from agentcontract.integrations.codex.models import (
    PostToolUsePayload,
    PreToolUsePayload,
    SessionStartPayload,
    StopPayload,
    UserPromptSubmitPayload,
)
from agentcontract.integrations.codex.state import CodexSessionStore


def test_lifecycle_workflow_end_to_end(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "codex_e2e_session"

    # 1. SessionStart
    start_payload = SessionStartPayload(session_id=session_id, hook_event_name="SessionStart")
    code, resp = handle_session_start(start_payload, store)
    assert code == 0
    assert store.session_exists(session_id)

    # 2. UserPromptSubmit: includes protected file requirement
    prompt_payload = UserPromptSubmitPayload(
        session_id=session_id,
        hook_event_name="UserPromptSubmit",
        prompt="Inspect src/app.py, run tests. Do not modify or write to secrets/prod.key under any circumstances.",
    )
    code, resp = handle_user_prompt_submit(prompt_payload, store)
    assert code == 0
    assert "active constraint(s) registered" in resp["hookSpecificOutput"]["additionalContext"]

    # Verify constraint is in session ledger
    _, ledger, _, _ = store.get_or_create_session(session_id)
    active = ledger.list_active()
    assert len(active) == 1
    assert "secrets/prod.key" in active[0].scope.paths

    # 3. Duplicate UserPromptSubmit: does not create duplicate constraints
    code, _ = handle_user_prompt_submit(prompt_payload, store)
    assert code == 0
    _, ledger_after, _, _ = store.get_or_create_session(session_id)
    assert len(ledger_after.list_active()) == 1

    # 4. PreToolUse: Allowed read_file
    allow_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="read_file",
        tool_input={"path": "src/app.py"},
        tool_use_id="call_read_1",
    )
    code, resp = handle_pre_tool_use(allow_payload, store)
    assert code == 0
    assert resp == {}

    # 5. PostToolUse: Record read_file result
    post_read = PostToolUsePayload(
        session_id=session_id,
        hook_event_name="PostToolUse",
        tool_name="read_file",
        tool_input={"path": "src/app.py"},
        tool_use_id="call_read_1",
        tool_response="def main(): pass",
    )
    code, _ = handle_post_tool_use(post_read, store)
    assert code == 0

    # 6. PreToolUse: FORBIDDEN apply_patch modifying secrets/prod.key -> MUST BLOCK (structured DENY)
    bad_patch = """
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-pass
+return 0
--- a/secrets/prod.key
+++ b/secrets/prod.key
@@ -1 +1 @@
-old
+tampered
"""
    deny_patch_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        tool_input={"patch": bad_patch},
        tool_use_id="call_patch_bad",
    )
    code, resp = handle_pre_tool_use(deny_patch_payload, store)
    assert code == 0  # Clean hook execution returning structured DENY
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "BLOCK:" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # 7. PreToolUse: FORBIDDEN Bash modifying secrets/prod.key -> MUST BLOCK
    deny_bash_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "rm -rf secrets/prod.key"},
        tool_use_id="call_bash_bad",
    )
    code, resp = handle_pre_tool_use(deny_bash_payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"

    # 8. PreToolUse & PostToolUse: Running pytest (Allowed)
    test_run_pre = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "pytest"},
        tool_use_id="call_pytest_1",
    )
    code, _ = handle_pre_tool_use(test_run_pre, store)
    assert code == 0

    test_run_post = PostToolUsePayload(
        session_id=session_id,
        hook_event_name="PostToolUse",
        tool_name="Bash",
        tool_input={"command": "pytest"},
        tool_use_id="call_pytest_1",
        tool_response={"exit_code": 0, "output": "2 passed in 0.05s"},
    )
    code, _ = handle_post_tool_use(test_run_post, store)
    assert code == 0

    # 9. Stop: Evaluate completion claims
    stop_payload = StopPayload(
        session_id=session_id,
        hook_event_name="Stop",
        last_assistant_message="Refactored the project. Ran pytest and all tests passed with exit code 0. Also generated secrets/prod.key.",
    )
    code, resp = handle_stop(stop_payload, store)
    assert code == 0
    context = resp["hookSpecificOutput"]["additionalContext"]
    assert "Verified: 1" in context  # pytest succeeded
    assert "Unverified: 1" in context  # secrets/prod.key was blocked, never generated!


def test_run_hook_stdin_dispatch(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    stdin_json = json.dumps({
        "session_id": "dispatch_sess",
        "hook_event_name": "SessionStart",
    })
    code, resp = run_hook(stdin_data=stdin_json, session_store=store)
    assert code == 0


def test_run_hook_malformed_json_fails_safely(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    code, resp = run_hook(stdin_data="{invalid json...", session_store=store)
    assert code == 0
    assert resp == {}


def test_run_hook_empty_input_fails_safely(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    code, resp = run_hook(stdin_data="", session_store=store)
    assert code == 0
    assert resp == {}


def test_opaque_bash_fail_closed_with_active_hard_constraint(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_opaque_test"

    # Add hard filesystem constraint to session ledger
    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_hard_secret",
                name="protect_secrets",
                description="Do not touch secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(target_type="filesystem", paths=("secrets/prod.key",)),
            )
        )

    # 1. Opaque python script -> MUST BLOCK fail-closed (exit 2)
    py_script_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "python script.py"},
    )
    code, resp = handle_pre_tool_use(py_script_payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "fail-closed policy" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # 2. Opaque inline python -> MUST BLOCK fail-closed (deny)
    py_c_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "python -c \"import os; os.remove('secrets/prod.key')\""},
    )
    code, resp = handle_pre_tool_use(py_c_payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"

    # 3. Opaque shell script -> MUST BLOCK fail-closed (deny)
    sh_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "bash run_indirection.sh"},
    )
    code, resp = handle_pre_tool_use(sh_payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"

    # 4. Destructive wildcard rm -> MUST BLOCK fail-closed (deny)
    rm_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "rm -rf *"},
    )
    code, resp = handle_pre_tool_use(rm_payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"

    # 5. Safe test runner -> MUST BE ALLOWED (exit 0)
    pytest_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "pytest tests/test_app.py"},
    )
    code, resp = handle_pre_tool_use(pytest_payload, store)
    assert code == 0
    assert resp == {}

    # 6. Safe inspection command -> MUST BE ALLOWED (exit 0)
    cat_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "cat src/app.py"},
    )
    code, resp = handle_pre_tool_use(cat_payload, store)
    assert code == 0
    assert resp == {}


def test_opaque_bash_allowed_when_no_hard_filesystem_constraints(tmp_path: Path) -> None:
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_no_constraints"

    # With empty ledger, opaque python script should be allowed
    py_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "python setup.py build"},
    )
    code, resp = handle_pre_tool_use(py_payload, store)
    assert code == 0
    assert resp == {}


def test_mixed_patch_with_file_write_only_constraint_is_denied(tmp_path: Path) -> None:
    # Regression for Blocker 2:
    # secrets/prod.key is protected ONLY against FILE_WRITE.
    # The patch deletes tmp.txt and modifies secrets/prod.key.
    # Previously, presence of "delete" caused entire action to be FILE_DELETE, evading FILE_WRITE constraint!
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_mixed_patch_block"

    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_write_only",
                name="no_write_secrets",
                description="Never write secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(
                    target_type="filesystem",
                    paths=("secrets/prod.key",),
                    actions=("FILE_WRITE",),  # ONLY FILE_WRITE
                ),
            )
        )

    mixed_patch = """
*** Delete File: tmp.txt
*** Update File: secrets/prod.key
@@ -1 +1 @@
-old
+tampered
"""
    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        tool_input={"patch": mixed_patch},
        tool_use_id="call_mixed_01",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "BLOCK:" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_mixed_patch_with_file_delete_only_constraint_is_denied(tmp_path: Path) -> None:
    # Symmetrical check: secrets/prod.key is protected ONLY against FILE_DELETE.
    # The patch updates tmp.txt and deletes secrets/prod.key.
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_mixed_delete_block"

    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_delete_only",
                name="no_delete_secrets",
                description="Never delete secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(
                    target_type="filesystem",
                    paths=("secrets/prod.key",),
                    actions=("FILE_DELETE",),  # ONLY FILE_DELETE
                ),
            )
        )

    mixed_patch = """
*** Update File: tmp.txt
@@ -1 +1 @@
-old
+new
*** Delete File: secrets/prod.key
"""
    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        tool_input={"patch": mixed_patch},
        tool_use_id="call_mixed_02",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "BLOCK:" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_dynamic_variable_bash_denied_under_hard_constraints(tmp_path: Path) -> None:
    # Regression for Blocker 1:
    # Set-Content -LiteralPath $env:TARGET -Value hacked
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_dynamic_var_test"

    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_hard_secret",
                name="protect_secrets",
                description="Do not touch secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(target_type="filesystem", paths=("secrets/prod.key",)),
            )
        )

    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "Set-Content -LiteralPath $env:TARGET -Value hacked"},
        tool_use_id="call_dynamic_var",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "fail-closed policy" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_unknown_command_denied_under_hard_constraints(tmp_path: Path) -> None:
    # Regression for Blocker 1: unknown commands must fail-closed under HARD file constraints
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_unknown_cmd_test"

    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_hard_secret",
                name="protect_secrets",
                description="Do not touch secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(target_type="filesystem", paths=("secrets/prod.key",)),
            )
        )

    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "unknown_file_mutator --target secrets/prod.key"},
        tool_use_id="call_unknown_cmd",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "fail-closed" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_corrupted_ledger_fails_closed_in_pre_tool_use(tmp_path: Path) -> None:
    # Regression for Blocker 3: corrupted ledger must DENY and never overwrite
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_corrupt_ledger_block"

    # Create session
    store.get_or_create_session(session_id)
    ledger_path = store.get_session_dir(session_id) / "ledger.json"
    corrupt_content = "NOT_VALID_JSON{:::broken"
    ledger_path.write_text(corrupt_content, encoding="utf-8")

    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "cat src/app.py"},
        tool_use_id="call_corrupt_check",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "corrupted or unreadable: fail-closed safety block" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # File on disk remains intact and was not overwritten
    assert ledger_path.read_text(encoding="utf-8") == corrupt_content


def test_mixed_patch_allowed_when_only_unrelated_path_is_deleted(tmp_path: Path) -> None:
    # Regression for Blocker 1: Update on secrets/prod.key + Delete on tmp.txt
    # When constraint DENY FILE_DELETE on secrets/prod.key exists, MUST ALLOW because secrets/prod.key is only written, not deleted.
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_mixed_patch_allowed"

    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_deny_delete_secret",
                name="no_delete_secrets",
                description="Do not delete secrets/prod.key (writes are permitted)",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(
                    target_type="filesystem",
                    paths=("secrets/prod.key",),
                    actions=("FILE_DELETE",),
                ),
            )
        )

    patch_text = """*** Begin Patch
*** Update File: secrets/prod.key
@@ -1,1 +1,1 @@
-old
+new
*** Delete File: tmp.txt
@@ -1,1 +0,0 @@
-temp
*** End Patch"""

    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        tool_input={"patch": patch_text},
        tool_use_id="call_patch_allowed",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    # Must NOT false-BLOCK: write on secrets/prod.key is permitted, and delete is on tmp.txt (returns empty dict on allow)
    assert resp == {}


def test_mixed_patch_denied_when_matched_pair_violates(tmp_path: Path) -> None:
    # Regression for Blocker 1: Update on secrets/prod.key + Delete on tmp.txt
    # When constraint DENY FILE_WRITE on secrets/prod.key exists, MUST BLOCK.
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_mixed_patch_denied"

    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_deny_write_secret",
                name="no_write_secrets",
                description="Do not modify secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(
                    target_type="filesystem",
                    paths=("secrets/prod.key",),
                    actions=("FILE_WRITE",),
                ),
            )
        )

    patch_text = """*** Begin Patch
*** Update File: secrets/prod.key
@@ -1,1 +1,1 @@
-old
+new
*** Delete File: tmp.txt
@@ -1,1 +0,0 @@
-temp
*** End Patch"""

    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        tool_input={"patch": patch_text},
        tool_use_id="call_patch_denied",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "BLOCK: Action violates constraint" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_uninspectable_patch_denied_under_hard_constraints(tmp_path: Path) -> None:
    # Regression for Blocker 1: uninspectable patch with no extractable paths must fail-closed under HARD constraints
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_uninspectable_patch"

    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_hard_secret",
                name="protect_secrets",
                description="Do not touch secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(target_type="filesystem", paths=("secrets/prod.key",)),
            )
        )

    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        tool_input={"patch": "completely corrupted diff with no files @@ ++ --"},
        tool_use_id="call_uninspectable_patch",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Uninspectable patch with no deterministically extractable target paths" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_missing_ledger_on_existing_session_blocks_pre_tool_use(tmp_path: Path) -> None:
    # Regression for Blocker 2: existing session missing ledger.json must fail-closed with deny
    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    session_id = "sess_missing_ledger_fail_closed"

    # 1. Initialize session with a HARD constraint
    with store.session_transaction(session_id) as tx:
        from agentcontract.constraints.models import (
            Constraint,
            ConstraintProvenance,
            ConstraintScope,
            ConstraintSource,
            ConstraintStrength,
            RuleEffect,
        )
        tx.ledger.add(
            Constraint(
                id="c_hard_secret",
                name="protect_secrets",
                description="Do not touch secrets/prod.key",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(source=ConstraintSource.USER, author="User"),
                scope=ConstraintScope(target_type="filesystem", paths=("secrets/prod.key",)),
            )
        )

    # 2. Delete ledger.json from disk
    ledger_file = store.get_session_dir(session_id) / "ledger.json"
    assert ledger_file.is_file()
    ledger_file.unlink()

    # 3. Call PreToolUse hook
    payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "cat src/app.py"},
        tool_use_id="call_check_missing_ledger",
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Missing constraint ledger file for existing session" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_pre_tool_use_malformed_inputs_fail_closed(tmp_path: Path) -> None:
    # Regression for Blocker 3: empty stdin, bad JSON, missing tool_name, invalid tool_input
    store = CodexSessionStore(base_dir=tmp_path / "sessions")

    # 1. Empty stdin
    code, resp = run_hook(stdin_data="", event_name="PreToolUse", session_store=store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Empty or missing stdin payload" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # 2. Malformed JSON with PreToolUse event name
    code, resp = run_hook(stdin_data="{ broken json", event_name="PreToolUse", session_store=store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Malformed or unparseable JSON" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # 3. Malformed JSON containing PreToolUse in raw text without explicit event_name
    code, resp = run_hook(stdin_data="{\"hook_event_name\": \"PreToolUse\", corrupted...", session_store=store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"

    # 4. Missing tool_name
    bad_payload = json.dumps({"session_id": "sess_bad", "hook_event_name": "PreToolUse"})
    code, resp = run_hook(stdin_data=bad_payload, session_store=store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Invalid PreToolUse payload schema" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # 5. Invalid tool_input (not a dictionary/mapping)
    bad_input_payload = json.dumps({
        "session_id": "sess_bad",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": "should_be_a_dict_not_a_string",
    })
    code, resp = run_hook(stdin_data=bad_input_payload, session_store=store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Invalid PreToolUse payload schema" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # 6. Non-dict root JSON
    code, resp = run_hook(stdin_data="[1, 2, 3]", event_name="PreToolUse", session_store=store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "must be an object/dict" in resp["hookSpecificOutput"]["permissionDecisionReason"]


def test_pre_tool_use_cli_subprocess_fail_closed() -> None:
    # Regression for Blocker 3: CLI execution of hooks PreToolUse must fail-closed
    import subprocess
    import sys

    # Run with empty stdin
    res = subprocess.run(
        [sys.executable, "-m", "agentcontract.integrations.codex.hooks", "PreToolUse"],
        input="",
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"

    # Run with bad JSON
    res2 = subprocess.run(
        [sys.executable, "-m", "agentcontract.integrations.codex.hooks", "PreToolUse"],
        input="{ bad json",
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0
    data2 = json.loads(res2.stdout)
    assert data2["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_tool_use_lock_timeout_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for Round 4 Blocker 1: forced lock timeout must return structured DENY
    from agentcontract.integrations.codex.state import SessionLock

    def _fake_acquire(self: SessionLock) -> None:
        raise TimeoutError("Lock acquisition timed out after 10.0s")

    monkeypatch.setattr(SessionLock, "acquire", _fake_acquire)

    store = CodexSessionStore(base_dir=tmp_path / "sessions")
    payload = PreToolUsePayload(
        session_id="sess_timeout_test",
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "cat secrets/prod.key"},
    )
    code, resp = handle_pre_tool_use(payload, store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "timed out" in resp["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_pre_tool_use_unexpected_exception_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for Round 4 Blocker 1: unexpected internal error must return structured DENY
    store = CodexSessionStore(base_dir=tmp_path / "sessions")

    def _faulty_to_action(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Simulated unexpected fault in adapter")

    monkeypatch.setattr(CodexHookAdapter, "to_action", _faulty_to_action)

    payload_json = json.dumps({
        "session_id": "sess_fault_test",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo test"},
    })
    code, resp = run_hook(stdin_data=payload_json, event_name="PreToolUse", session_store=store)
    assert code == 0
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "fail-closed" in resp["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_pre_tool_use_cli_subprocess_forced_lock_timeout(tmp_path: Path) -> None:
    # Regression for Round 4 Blocker 1: CLI subprocess with forced lock timeout outputs structured DENY
    import subprocess
    import sys

    # Run CLI using a monkeypatched helper or script that triggers TimeoutError
    code_snippet = (
        "import sys, json; "
        "from agentcontract.integrations.codex.state import SessionLock; "
        "from agentcontract.integrations.codex.hooks import main; "
        "SessionLock.acquire = lambda self: (_ for _ in ()).throw(TimeoutError('Subprocess lock timed out')); "
        "main()"
    )
    payload_json = json.dumps({
        "session_id": "sess_cli_timeout",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo test"},
    })
    res = subprocess.run(
        [sys.executable, "-c", code_snippet, "PreToolUse"],
        input=payload_json,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "timed out" in data["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_pre_tool_use_cli_subprocess_allow_empty_stdout() -> None:
    """Verify that CLI execution of PreToolUse on ALLOW returns exit 0 with empty stdout per Codex CLI v0.162.0+ protocol."""
    import subprocess
    import sys

    payload_json = json.dumps({
        "session_id": "sess_cli_allow",
        "hook_event_name": "PreToolUse",
        "tool_name": "read_file",
        "tool_input": {"path": "src/app.py"},
    })
    res = subprocess.run(
        [sys.executable, "-m", "agentcontract.integrations.codex.hooks", "PreToolUse"],
        input=payload_json,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""



