"""Unit tests for OpenCode adapter, bridge, and SpecGuard integration."""

import json
from pathlib import Path
import tempfile
import pytest

from agentcontract.adapters.opencode import (
    build_opencode_plugin_js,
    evaluate_opencode_tool_call,
    load_manifest_constraints,
    normalize_rel_path,
    parse_opencode_tool_to_action,
)
from agentcontract.guard.models import ActionKind, DecisionKind


def test_normalize_rel_path():
    assert normalize_rel_path("src\\app.py") == "src/app.py"
    assert normalize_rel_path("./src/app.py") == "src/app.py"
    assert normalize_rel_path("config/prod.key") == "config/prod.key"


def test_parse_opencode_tool_to_action():
    act_write = parse_opencode_tool_to_action(
        tool="write",
        args={"filePath": "config\\prod.key", "content": "secret"},
        call_id="call_1",
        session_id="ses_1",
    )
    assert act_write.action_kind == ActionKind.FILE_WRITE
    assert "config/prod.key" in act_write.paths
    assert act_write.target_path == "config/prod.key"

    act_edit = parse_opencode_tool_to_action(
        tool="edit",
        args={"file_path": "src/app.py", "oldString": "a", "newString": "b"},
        call_id="call_2",
        session_id="ses_1",
    )
    assert act_edit.action_kind == ActionKind.FILE_WRITE
    assert "src/app.py" in act_edit.paths

    act_read = parse_opencode_tool_to_action(
        tool="read",
        args={"filePath": "README.md"},
        call_id="call_3",
        session_id="ses_1",
    )
    assert act_read.action_kind == ActionKind.FILE_READ
    assert "README.md" in act_read.paths

    act_bash = parse_opencode_tool_to_action(
        tool="bash",
        args={"command": "cat config/prod.key > backup.txt"},
        call_id="call_4",
        session_id="ses_1",
    )
    assert act_bash.action_kind == ActionKind.COMMAND_EXEC
    assert any("config/prod.key" in p for p in act_bash.paths)


def test_evaluate_opencode_tool_call_allow_and_block(tmp_path: Path):
    manifest_data = {
        "version": "1.0",
        "constraints": [
            {
                "id": "c_protect_prod",
                "name": "Protect Prod",
                "description": "Never modify config/prod.key",
                "strength": "HARD",
                "effect": "DENY",
                "scope": {
                    "target_type": "filesystem",
                    "paths": ["config/prod.key"],
                    "actions": ["write", "modify", "update", "delete", "edit"],
                },
            }
        ],
    }
    manifest_dir = tmp_path / ".agentcontract"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    # 1. Allowed file write
    res_allow = evaluate_opencode_tool_call(
        project_dir=tmp_path,
        tool="write",
        args={"filePath": "config/dev.env", "content": "ENV=dev"},
        call_id="call_allowed_1",
        session_id="ses_1",
    )
    assert res_allow["decision"] == "ALLOW"
    assert len(res_allow["violating_constraint_ids"]) == 0

    # 2. Blocked file edit targeting protected path
    res_block = evaluate_opencode_tool_call(
        project_dir=tmp_path,
        tool="edit",
        args={"filePath": "config/prod.key", "newString": "HACKED"},
        call_id="call_blocked_1",
        session_id="ses_1",
    )
    assert res_block["decision"] == "BLOCK"
    assert "c_protect_prod" in res_block["violating_constraint_ids"]

    # 3. Check trace log exists and contains both decisions
    trace_file = manifest_dir / "guard_trace.jsonl"
    assert trace_file.exists()
    lines = [json.loads(l) for l in trace_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[0]["decision"] == "ALLOW"
    assert lines[1]["decision"] == "BLOCK"


def test_build_opencode_plugin_js():
    js_content = build_opencode_plugin_js(python_exe="python.exe")
    assert "AgentContractPlugin" in js_content
    assert "tool.execute.before" in js_content
    assert "tool.execute.after" in js_content
    assert "AgentContract BLOCK:" in js_content
