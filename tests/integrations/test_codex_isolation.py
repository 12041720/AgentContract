"""Comprehensive regression and isolation tests verifying zero external side effects on Codex CLI & Desktop."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import pytest

from agentcontract.cli import main
from agentcontract.integrations.codex.cli import (
    audit_hooks,
    install_hooks,
    status_hooks,
    uninstall_hooks,
)
from agentcontract.integrations.codex.state import CodexSessionStore


def test_temporary_project_install_status_uninstall_isolation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Requirement 1: A temporary project with no hooks: install, use, uninstall only affects that project."""
    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    # 1. Install into proj_a only
    ret = install_hooks(project_dir=proj_a)
    assert ret == 0
    hooks_file_a = proj_a / ".codex" / "hooks.json"
    assert hooks_file_a.is_file()

    # Verify proj_b has no hooks
    assert not (proj_b / ".codex").exists()

    # Verify hooks content in proj_a
    data_a = json.loads(hooks_file_a.read_text(encoding="utf-8"))
    assert "hooks" in data_a
    assert "PreToolUse" in data_a["hooks"]
    assert "SessionStart" in data_a["hooks"]

    # 2. Check status of proj_a and proj_b
    status_ret_a = status_hooks(project_dir=proj_a)
    assert status_ret_a == 0
    captured_a = capsys.readouterr()
    assert "AgentContract Active: Yes" in captured_a.out
    assert "Project-local only" in captured_a.out

    status_ret_b = status_hooks(project_dir=proj_b)
    assert status_ret_b == 0
    captured_b = capsys.readouterr()
    assert "Not installed" in captured_b.out

    # 3. Uninstall from proj_a
    ret_uninst = uninstall_hooks(project_dir=proj_a)
    assert ret_uninst == 0
    assert not hooks_file_a.exists()
    assert not (proj_a / ".codex").exists()
    assert not (proj_b / ".codex").exists()


def test_merge_and_preserve_foreign_hooks(tmp_path: Path) -> None:
    """Requirement 2: A project with non-AgentContract hooks: install merges, idempotence, uninstall restores original content semantically."""
    proj = tmp_path / "foreign_proj"
    codex_dir = proj / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"

    # Pre-existing foreign hooks configuration
    initial_foreign_config: dict[str, Any] = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "node scripts/third_party_linter.js",
                        }
                    ],
                }
            ],
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python scripts/telemetry_start.py",
                        }
                    ],
                }
            ],
        }
    }
    hooks_file.write_text(json.dumps(initial_foreign_config, indent=2), encoding="utf-8")

    # 1. Install hooks: must merge without overwriting
    ret = install_hooks(project_dir=proj)
    assert ret == 0

    merged_data = json.loads(hooks_file.read_text(encoding="utf-8"))
    hooks_map = merged_data["hooks"]

    # Verify foreign entries are preserved in PreToolUse and SessionStart
    pre_tool_commands = [h["command"] for entry in hooks_map["PreToolUse"] for h in entry.get("hooks", [])]
    assert "node scripts/third_party_linter.js" in pre_tool_commands
    assert any("agentcontract.integrations.codex.hooks PreToolUse" in cmd for cmd in pre_tool_commands)

    start_commands = [h["command"] for entry in hooks_map["SessionStart"] for h in entry.get("hooks", [])]
    assert "python scripts/telemetry_start.py" in start_commands
    assert any("agentcontract.integrations.codex.hooks SessionStart" in cmd for cmd in start_commands)

    # 2. Idempotence: repeated installation must not multiply hooks
    ret_again = install_hooks(project_dir=proj)
    assert ret_again == 0

    data_after_second_install = json.loads(hooks_file.read_text(encoding="utf-8"))
    pre_tool_entries = data_after_second_install["hooks"]["PreToolUse"]
    ac_pre_tool = [
        e for e in pre_tool_entries
        if any("agentcontract" in h.get("command", "") for h in e.get("hooks", []))
    ]
    assert len(ac_pre_tool) == 1, "Idempotent install must not duplicate AgentContract entries"

    # 3. Uninstall: must remove ONLY AgentContract entries and restore original foreign hooks
    ret_uninst = uninstall_hooks(project_dir=proj)
    assert ret_uninst == 0
    assert hooks_file.is_file(), "File must NOT be deleted when foreign hooks remain"

    restored_data = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert restored_data == initial_foreign_config, "Uninstall must restore foreign hooks exactly"


def test_invalid_hooks_file_safe_failure(tmp_path: Path) -> None:
    """Requirement 3: An existing invalid hooks file: explicit safe failure without overwriting."""
    proj = tmp_path / "corrupted_proj"
    codex_dir = proj / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"

    malformed_content = "{ invalid json syntax: true, missing quotes ..."
    hooks_file.write_text(malformed_content, encoding="utf-8")

    # Install should safely fail and NOT overwrite corrupted file
    ret_install = install_hooks(project_dir=proj)
    assert ret_install == 1
    assert hooks_file.read_text(encoding="utf-8") == malformed_content

    # Uninstall should safely fail and NOT delete corrupted file
    ret_uninstall = uninstall_hooks(project_dir=proj)
    assert ret_uninstall == 1
    assert hooks_file.read_text(encoding="utf-8") == malformed_content


def test_dangerous_root_and_home_targets_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Guardrail: Refuse to install hooks directly at system root or user home directory."""
    home_dir = tmp_path / "fake_home"
    home_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home_dir)

    ret = install_hooks(project_dir=home_dir)
    assert ret == 1
    assert not (home_dir / ".codex").exists()


def test_sibling_workspaces_isolation(tmp_path: Path) -> None:
    """Requirement 4: Two sibling workspaces, only A opted in: hooks never activate in B."""
    ws_a = tmp_path / "ws_opted_in"
    ws_b = tmp_path / "ws_unopted"
    ws_a.mkdir()
    ws_b.mkdir()

    install_hooks(project_dir=ws_a)
    assert (ws_a / ".codex" / "hooks.json").is_file()
    assert not (ws_b / ".codex").exists()

    # Create session store in A
    store_a = CodexSessionStore(base_dir=ws_a / ".agentcontract" / "sessions")
    store_a.get_or_create_session("sess_isolated_a")
    assert store_a.session_exists("sess_isolated_a")

    # Verify B is completely untouched and has no session store
    store_b = CodexSessionStore(base_dir=ws_b / ".agentcontract" / "sessions")
    assert not store_b.session_exists("sess_isolated_a")
    assert not (ws_b / ".agentcontract").exists()


def test_audit_command_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Requirement C & 7: Audit command performs read-only checks without modifying files."""
    proj = tmp_path / "audit_test_project"
    proj.mkdir()
    install_hooks(project_dir=proj)

    # Pre-snapshot of proj directory
    pre_state = list(proj.rglob("*"))

    ret = audit_hooks(project_dir=proj)
    assert ret == 0
    captured = capsys.readouterr()
    assert "AgentContract Codex Isolation Audit Report" in captured.out
    assert "Target Project" in captured.out
    assert "Isolation Assessment" in captured.out

    # Post-check: nothing was modified by audit
    post_state = list(proj.rglob("*"))
    assert pre_state == post_state


def test_import_and_test_suite_zero_global_effects() -> None:
    """Requirement 6: Importing AgentContract and running standard logic does not touch user's ~/.codex."""
    real_codex = Path.home() / ".codex"
    if real_codex.exists():
        # Check that no agentcontract file was written at top level
        assert not (real_codex / "agentcontract").exists()
        assert not (real_codex / "hooks.json.bak").exists()


def test_cli_subcommand_audit_integration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test 'agentcontract codex audit --project <dir>' command routing."""
    proj = tmp_path / "cli_audit_proj"
    proj.mkdir()

    ret = main(["codex", "audit", "--project", str(proj)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "AgentContract Codex Isolation Audit Report" in captured.out
