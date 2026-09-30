"""Integration tests for Codex lifecycle hook executions and SpecGuard/EvidenceGate gating."""

import json
from pathlib import Path
import pytest

from agentcontract.constraints.models import ConstraintStatus
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
    assert resp["hookSpecificOutput"]["permissionDecision"] == "allow"

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

    # 6. PreToolUse: FORBIDDEN apply_patch modifying secrets/prod.key -> MUST BLOCK (exit code 2)
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
    assert code == 2  # Hard BLOCK exit code
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "BLOCK:" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    # 7. PreToolUse: FORBIDDEN Bash modifying secrets/prod.key -> MUST BLOCK (exit code 2)
    deny_bash_payload = PreToolUsePayload(
        session_id=session_id,
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "rm -rf secrets/prod.key"},
        tool_use_id="call_bash_bad",
    )
    code, resp = handle_pre_tool_use(deny_bash_payload, store)
    assert code == 2
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
