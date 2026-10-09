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


def test_mixed_matcher_group_uninstall_preserves_third_party_handlers(tmp_path: Path) -> None:
    """Blocker 1: Mixed matcher group containing both AgentContract and third-party handlers must retain third-party handler upon uninstall."""
    proj = tmp_path / "mixed_group_proj"
    codex_dir = proj / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"

    # Pre-existing mixed matcher group
    mixed_config = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -m agentcontract.integrations.codex.hooks PreToolUse",
                        },
                        {
                            "type": "command",
                            "command": "node scripts/third_party_guard.js",
                        },
                    ],
                }
            ]
        }
    }
    hooks_file.write_text(json.dumps(mixed_config, indent=2), encoding="utf-8")

    # 1. Idempotent install: AgentContract already in PreToolUse, should not duplicate
    ret_install = install_hooks(project_dir=proj)
    assert ret_install == 0
    data_after_install = json.loads(hooks_file.read_text(encoding="utf-8"))
    handlers = data_after_install["hooks"]["PreToolUse"][0]["hooks"]
    ac_handlers = [h for h in handlers if "agentcontract" in h.get("command", "")]
    assert len(ac_handlers) == 1, "Idempotent install must not duplicate AgentContract handler"

    # 2. Uninstall: MUST remove only the AgentContract handler and keep the group & third-party handler intact
    ret_uninstall = uninstall_hooks(project_dir=proj)
    assert ret_uninstall == 0
    assert hooks_file.is_file(), "hooks.json must remain because third-party handler is still present"

    data_after_uninstall = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert "PreToolUse" in data_after_uninstall["hooks"]
    remaining_group = data_after_uninstall["hooks"]["PreToolUse"][0]
    assert remaining_group.get("matcher") == ".*"
    remaining_handlers = remaining_group.get("hooks", [])
    assert len(remaining_handlers) == 1
    assert remaining_handlers[0]["command"] == "node scripts/third_party_guard.js"


def test_malformed_hook_structures_rejected(tmp_path: Path) -> None:
    """Blocker 2: Existing malformed structural shapes must explicitly fail safely without overwriting."""
    malformed_cases = [
        ("hooks_as_list", '{"hooks": []}'),
        ("event_as_dict", '{"hooks": {"PreToolUse": {"hooks": []}}}'),
        ("event_as_null", '{"hooks": {"PreToolUse": null}}'),
        ("event_as_string", '{"hooks": {"PreToolUse": "invalid"}}'),
        ("entry_hooks_not_list", '{"hooks": {"PreToolUse": [{"hooks": "not_a_list"}]}}'),
        ("handler_not_dict", '{"hooks": {"PreToolUse": [{"hooks": ["not_a_dict"]}]}}'),
    ]

    for label, bad_json in malformed_cases:
        case_proj = tmp_path / f"malformed_{label}"
        codex_dir = case_proj / ".codex"
        codex_dir.mkdir(parents=True)
        hooks_file = codex_dir / "hooks.json"
        hooks_file.write_text(bad_json, encoding="utf-8")

        # install_hooks must reject and leave file completely intact
        ret_inst = install_hooks(project_dir=case_proj)
        assert ret_inst == 1, f"install_hooks did not reject malformed case: {label}"
        assert hooks_file.read_text(encoding="utf-8") == bad_json, f"File was overwritten in case: {label}"

        # uninstall_hooks must reject and leave file completely intact
        ret_uninst = uninstall_hooks(project_dir=case_proj)
        assert ret_uninst == 1, f"uninstall_hooks did not reject malformed case: {label}"
        assert hooks_file.read_text(encoding="utf-8") == bad_json, f"File was overwritten in case: {label}"


def test_audit_detects_residual_config_toml_without_cache(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Blocker 3: Audit must detect residual [plugins.'agentcontract@...'] in config.toml even with zero cache entries."""
    fake_codex_home = tmp_path / "fake_codex_home"
    fake_codex_home.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(fake_codex_home))

    # Synthetic config.toml containing residual enabled plugin entry from real codex plugin add
    config_toml_content = (
        'model = "gpt-5.6-sol"\n'
        '\n'
        '[plugins."agentcontract@test_market_123456"]\n'
        'enabled = true\n'
    )
    (fake_codex_home / "config.toml").write_text(config_toml_content, encoding="utf-8")
    # Verify plugins/cache does NOT exist
    assert not (fake_codex_home / "plugins" / "cache").exists()

    proj = tmp_path / "audit_test_project"
    proj.mkdir()

    ret = audit_hooks(project_dir=proj)
    assert ret == 0
    captured = capsys.readouterr()

    # Must detect residual and must NOT report CLEAN / PASSED
    assert "RESIDUAL" in captured.out
    assert "agentcontract@test_market_123456" in captured.out
    assert "[CLEAN] Zero External Side Effects Confirmed" not in captured.out
    assert "[PASSED] Zero External Side Effects Confirmed" not in captured.out
    assert "codex plugin remove agentcontract" in captured.out


def test_audit_clean_synthetic_home(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Blocker 3: Audit reports CLEAN when config.toml has only unrelated third-party plugins."""
    clean_home = tmp_path / "clean_home"
    clean_home.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(clean_home))

    config_toml_content = (
        'model = "gpt-5.6-sol"\n'
        '\n'
        '[plugins."unrelated_linter@openai-curated"]\n'
        'enabled = true\n'
    )
    (clean_home / "config.toml").write_text(config_toml_content, encoding="utf-8")

    proj = tmp_path / "clean_proj"
    proj.mkdir()

    ret = audit_hooks(project_dir=proj)
    assert ret == 0
    captured = capsys.readouterr()
    assert "[CLEAN] Zero External Side Effects Confirmed" in captured.out
    assert "RESIDUAL" not in captured.out


def test_root_path_rejection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Blocker 4: install_hooks, uninstall_hooks, and status_hooks must reject filesystem root paths."""
    fake_root = Path("C:\\") if sys.platform == "win32" else Path("/")

    # Safely mock resolve to return root path without ever touching the real system root
    monkeypatch.setattr(Path, "resolve", lambda self: fake_root)

    dummy = tmp_path / "dummy_root"
    assert install_hooks(project_dir=dummy) == 1
    assert uninstall_hooks(project_dir=dummy) == 1
    assert status_hooks(project_dir=dummy) == 1


def test_cli_subcommand_audit_integration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test 'agentcontract codex audit --project <dir>' command routing."""
    proj = tmp_path / "cli_audit_proj"
    proj.mkdir()

    ret = main(["codex", "audit", "--project", str(proj)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "AgentContract Codex Isolation Audit Report" in captured.out

