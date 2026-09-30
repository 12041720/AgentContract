"""Tests for CodexHookAdapter normalization, patch parsing, and command extraction."""

from agentcontract.constraints.models import ConstraintStrength, RuleEffect
from agentcontract.guard.models import ActionKind
from agentcontract.integrations.codex.adapter import (
    CodexHookAdapter,
    parse_command_paths,
    parse_patch_paths,
)
from agentcontract.integrations.codex.models import (
    PostToolUsePayload,
    PreToolUsePayload,
)
from agentcontract.trace.models import ToolResultStatus


def test_parse_patch_paths_unified_diff() -> None:
    patch = """
diff --git a/src/main.py b/src/main.py
index 1234567..89abcdef 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,3 @@
-print("hello")
+print("world")
diff --git a/secrets/prod.key b/secrets/prod.key
--- a/secrets/prod.key
+++ b/secrets/prod.key
@@ -1 +1 @@
-old_key
+leaked_key
"""
    paths = parse_patch_paths(patch)
    assert "src/main.py" in paths
    assert "secrets/prod.key" in paths
    assert len(paths) == 2


def test_parse_patch_paths_with_dev_null_and_index() -> None:
    patch = """
Index: config/settings.json
===================================================================
--- config/settings.json
+++ /dev/null
@@ -1,2 +0,0 @@
-{ "debug": true }
"""
    paths = parse_patch_paths(patch)
    assert paths == ("config/settings.json",)


def test_parse_command_paths() -> None:
    # 1. Output redirection
    cmd1 = "echo 'danger' > secrets/prod.key"
    assert "secrets/prod.key" in parse_command_paths(cmd1)

    # 2. Append redirection
    cmd2 = "python build.py >> output/build.log"
    assert "output/build.log" in parse_command_paths(cmd2)

    # 3. rm command
    cmd3 = "rm -rf secrets/prod.key"
    assert "secrets/prod.key" in parse_command_paths(cmd3)

    # 4. pytest execution
    cmd4 = "pytest tests/test_unit.py"
    assert "tests/test_unit.py" in parse_command_paths(cmd4)


def test_to_action_apply_patch_multi_file() -> None:
    patch = """
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-a
+b
--- a/secrets/prod.key
+++ b/secrets/prod.key
@@ -1 +1 @@
-secret
+exposed
"""
    payload = PreToolUsePayload(
        session_id="sess_123",
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        tool_input={"patch": patch},
    )
    action = CodexHookAdapter.to_action(payload)
    assert action.action_kind == ActionKind.FILE_WRITE
    assert action.target_type == "filesystem"
    assert "src/app.py" in action.paths
    assert "secrets/prod.key" in action.paths
    assert action.context["patch_paths_count"] == 2


def test_to_action_bash_preserves_command_and_paths() -> None:
    payload = PreToolUsePayload(
        session_id="sess_456",
        hook_event_name="PreToolUse",
        tool_name="Bash",
        tool_input={"command": "cat secrets/prod.key"},
    )
    action = CodexHookAdapter.to_action(payload)
    assert action.action_kind == ActionKind.COMMAND_EXEC
    assert action.operation == "cat secrets/prod.key"
    assert "secrets/prod.key" in action.paths


def test_to_action_mcp_tool_preserves_arguments() -> None:
    payload = PreToolUsePayload(
        session_id="sess_mcp",
        hook_event_name="PreToolUse",
        tool_name="custom_mcp_writer",
        tool_input={
            "file_path": "data/records.csv",
            "content": "id,val\n1,100",
            "metadata": {"source": "etl"},
        },
    )
    action = CodexHookAdapter.to_action(payload)
    assert action.action_kind == ActionKind.FILE_WRITE
    assert action.target_path == "data/records.csv"
    assert action.payload["metadata"] == {"source": "etl"}


def test_to_tool_call_and_result() -> None:
    pre = PreToolUsePayload(
        session_id="sess_call",
        hook_event_name="PreToolUse",
        tool_name="run_tests",
        tool_input={"command": "pytest"},
        tool_use_id="call_t123",
    )
    tc = CodexHookAdapter.to_tool_call(pre)
    assert tc.call_id == "call_t123"
    assert tc.tool_name == "run_tests"
    assert tc.arguments["command"] == "pytest"

    post_success = PostToolUsePayload(
        session_id="sess_call",
        hook_event_name="PostToolUse",
        tool_name="run_tests",
        tool_input={"command": "pytest"},
        tool_use_id="call_t123",
        tool_response={"exit_code": 0, "output": "all passed"},
    )
    tr_success = CodexHookAdapter.to_tool_result(post_success)
    assert tr_success.call_id == "call_t123"
    assert tr_success.status == ToolResultStatus.SUCCESS

    post_fail = PostToolUsePayload(
        session_id="sess_call",
        hook_event_name="PostToolUse",
        tool_name="run_tests",
        tool_input={"command": "pytest"},
        tool_use_id="call_t123",
        tool_response={"exit_code": 1, "error": "test failed"},
    )
    tr_fail = CodexHookAdapter.to_tool_result(post_fail)
    assert tr_fail.status == ToolResultStatus.ERROR


def test_extract_prompt_constraints_fallback() -> None:
    prompt = "Please refactor the code. Do not modify secrets/prod.key under any circumstances."
    constraints = CodexHookAdapter.extract_prompt_constraints(prompt, client=None)
    assert len(constraints) == 1
    c = constraints[0]
    assert c.strength == ConstraintStrength.HARD
    assert c.rule_effect == RuleEffect.DENY
    assert "secrets/prod.key" in c.scope.paths


def test_extract_completion_claims_fallback() -> None:
    prose = "I finished the task! Ran pytest and all tests passed with exit code 0. Also generated secrets/prod.key."
    claims = CodexHookAdapter.extract_completion_claims(prose, trace_id="tr_1", client=None)
    assert len(claims) == 2
    types = {c.claim_type.value for c in claims}
    assert "TESTS_PASSED" in types
    assert "FILE_EXISTS" in types
