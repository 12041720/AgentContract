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
    doctor_hooks,
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
    """Blocker 3: Audit must detect residual [plugins.'agentcontract@...'] in config.toml and recommend exact section removal."""
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

    # Must recommend targeted section removal rather than broad plugin removal when not cached
    assert "Stale configuration entries detected in" in captured.out
    assert 'Remove [plugins."agentcontract@test_market_123456"]' in captured.out
    assert "codex plugin remove agentcontract" not in captured.out


def test_audit_clean_synthetic_home(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Blocker 3: Audit reports PROJECT_SCOPED_ONLY and notes Desktop GUI remains UNVERIFIED without overclaiming."""
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
    assert "[PROJECT_SCOPED_ONLY]" in captured.out
    assert "Desktop GUI state" in captured.out
    assert "UNVERIFIED" in captured.out
    assert "[CLEAN] Zero External Side Effects Confirmed" not in captured.out
    assert "[PASSED] Zero External Side Effects Confirmed" not in captured.out
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


def test_junction_symlink_boundary_escape_rejection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Round 2 Blocker 1: Project-local .codex junction or symlink escaping project root must be rejected with zero changes to target."""
    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    external_target = proj_b / "external_codex"
    external_target.mkdir()
    sentinel_file = external_target / "sentinel.txt"
    sentinel_file.write_text("unrelated_external_data", encoding="utf-8")

    junction_link = proj_a / ".codex"

    # Create directory junction on Windows or symlink on POSIX
    created = False
    if sys.platform == "win32":
        try:
            import _winapi
            _winapi.CreateJunction(str(external_target), str(junction_link))
            created = True
        except Exception:
            pass

    if not created:
        try:
            junction_link.symlink_to(external_target, target_is_directory=True)
            created = True
        except Exception:
            pytest.skip("Filesystem does not support junction or symlink creation in test environment")

    assert junction_link.exists()

    # 1. install_hooks must refuse to install and return 1
    ret_install = install_hooks(project_dir=proj_a)
    assert ret_install == 1
    # Verify external target was NOT modified: hooks.json was NOT written
    assert not (external_target / "hooks.json").exists()
    assert sentinel_file.read_text(encoding="utf-8") == "unrelated_external_data"

    # 2. uninstall_hooks must refuse to operate and return 1
    ret_uninstall = uninstall_hooks(project_dir=proj_a)
    assert ret_uninstall == 1
    # External target must remain completely untouched
    assert sentinel_file.read_text(encoding="utf-8") == "unrelated_external_data"

    # 3. status_hooks must refuse to query redirected path and return 1
    ret_status = status_hooks(project_dir=proj_a)
    assert ret_status == 1

    # 4. audit_hooks must detect and report the escape without misleading output
    ret_audit = audit_hooks(project_dir=proj_a)
    assert ret_audit == 0
    captured = capsys.readouterr()
    assert "[SUSPICIOUS / ESCAPE DETECTED]" in captured.out or "[ESCAPE_DETECTED]" in captured.out


def test_uninstall_lossless_wrapped_foreign_config_with_empty_arrays(tmp_path: Path) -> None:
    """Round 2 Blocker 2: Uninstall must preserve top-level metadata, unknown keys, and foreign empty event arrays."""
    proj = tmp_path / "wrapped_foreign_proj"
    codex_dir = proj / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"

    # Exact reproduction structure from Round 2 review:
    # wrapped config with schemaVersion, foreign note, PreToolUse with AC hook, and empty foreign PostToolUse array
    initial_wrapped_config: dict[str, Any] = {
        "schemaVersion": 1,
        "note": "foreign metadata",
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -m agentcontract.integrations.codex.hooks PreToolUse",
                        }
                    ],
                }
            ],
            "PostToolUse": [],
        },
    }
    hooks_file.write_text(json.dumps(initial_wrapped_config, indent=2), encoding="utf-8")

    # 1. Uninstall should remove ONLY PreToolUse (AgentContract) and preserve foreign metadata & empty array
    ret_uninstall = uninstall_hooks(project_dir=proj)
    assert ret_uninstall == 0
    assert hooks_file.is_file(), "hooks.json must NOT be deleted because foreign metadata and empty array remain"

    data_after_uninstall = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert data_after_uninstall["schemaVersion"] == 1
    assert data_after_uninstall["note"] == "foreign metadata"
    assert "hooks" in data_after_uninstall
    assert data_after_uninstall["hooks"]["PostToolUse"] == [], "Empty foreign array PostToolUse: [] must be preserved"
    assert "PreToolUse" not in data_after_uninstall["hooks"], "PreToolUse containing only AgentContract must be removed"

    # 2. Test multi-event foreign config with empty foreign array and foreign handlers
    proj2 = tmp_path / "multi_foreign_proj"
    (proj2 / ".codex").mkdir(parents=True)
    hooks_file2 = proj2 / ".codex" / "hooks.json"
    multi_config = {
        "schemaVersion": 2,
        "customKey": "keep_this",
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {"type": "command", "command": "python -m agentcontract.integrations.codex.hooks PreToolUse"},
                    ],
                }
            ],
            "PostToolUse": [],
            "SessionStart": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {"type": "command", "command": "node scripts/custom_logger.js"},
                    ],
                }
            ],
        },
    }
    hooks_file2.write_text(json.dumps(multi_config, indent=2), encoding="utf-8")

    ret_uninst2 = uninstall_hooks(project_dir=proj2)
    assert ret_uninst2 == 0
    assert hooks_file2.is_file()
    data2 = json.loads(hooks_file2.read_text(encoding="utf-8"))
    assert data2["schemaVersion"] == 2
    assert data2["customKey"] == "keep_this"
    assert data2["hooks"]["PostToolUse"] == []
    assert len(data2["hooks"]["SessionStart"]) == 1
    assert data2["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "node scripts/custom_logger.js"
    assert "PreToolUse" not in data2["hooks"]


def test_cli_subcommand_audit_integration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test 'agentcontract codex audit --project <dir>' command routing."""
    proj = tmp_path / "cli_audit_proj"
    proj.mkdir()

    ret = main(["codex", "audit", "--project", str(proj)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "AgentContract Codex Isolation Audit Report" in captured.out


def test_environment_integrity_guard_resilience(tmp_path: Path) -> None:
    """Requirement: Environment integrity check must execute even if a test case raises failure/exception."""
    import hashlib

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    tracked = fake_home / "config.toml"
    tracked.write_text("model = 'init'\n", encoding="utf-8")

    initial_hash = hashlib.sha256(tracked.read_bytes()).hexdigest()

    teardown_executed = False
    caught_mutation = False

    def simulated_fixture():
        nonlocal teardown_executed, caught_mutation
        pre_h = hashlib.sha256(tracked.read_bytes()).hexdigest()
        try:
            yield
        finally:
            teardown_executed = True
            post_h = hashlib.sha256(tracked.read_bytes()).hexdigest()
            if post_h != pre_h:
                caught_mutation = True
                raise AssertionError("Guarded configuration mutated in-place!")

    # 1. Simulate a test that fails (raises ValueError) while also mutating a tracked file
    gen = simulated_fixture()
    next(gen)
    tracked.write_text("model = 'mutated'\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="Guarded configuration mutated in-place!"):
        try:
            raise ValueError("Simulated test failure")
        except Exception:
            # pytest fixture teardown executes on test exception via gen.throw or next
            gen.throw(ValueError("Simulated test failure"))

    assert teardown_executed is True, "Integrity check must execute on test failure"
    assert caught_mutation is True, "Integrity check must catch in-place mutations"


def test_doctor_hooks_on_installed_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test doctor_hooks on an installed project: verifies all 5 diagnostic categories and clean disposable smoke session."""
    proj = tmp_path / "doctor_installed_proj"
    proj.mkdir()

    # 1. Install hooks
    ret_install = install_hooks(project_dir=proj)
    assert ret_install == 0

    # 2. Run doctor
    ret_doctor = doctor_hooks(project_dir=proj)
    assert ret_doctor == 0

    captured = capsys.readouterr()
    assert "AgentContract Codex Doctor Report" in captured.out
    assert "[PASS] Project boundary containment verified" in captured.out
    assert "[PASS] hooks.json syntax, schema, and command handlers valid" in captured.out
    assert "[PASS] SessionStart hook executed successfully via subprocess" in captured.out
    assert "[PASS] PreToolUse hook invoked and processed inputs via subprocess" in captured.out
    assert "[PASS] Compliant action evaluated -> SpecGuard ALLOW recorded" in captured.out
    assert "[PASS] Forbidden action evaluated -> SpecGuard BLOCK recorded" in captured.out
    assert "[PASS] Authentic trace events recorded in session store" in captured.out
    assert "[PASS] ALLOW wire-format: exit code 0 with completely empty stdout (no input rewrite)" in captured.out
    assert "[PASS] BLOCK wire-format: structured JSON denial" in captured.out
    assert "[PASS] User global ~/.codex observed untouched" in captured.out
    assert "[PASS] AgentContract doctor executed zero elevated sandbox, ACL, or process termination commands" in captured.out
    assert "[PASS] Disposable smoke session resources cleaned up completely" in captured.out
    assert "[NOT OBSERVED] External system ACLs" in captured.out
    assert "Upstream Environment Advisory" in captured.out

    # 3. Verify disposable smoke session was completely cleaned up
    sessions_dir = proj / ".agentcontract" / "sessions"
    if sessions_dir.exists():
        remaining = list(sessions_dir.iterdir())
        assert not remaining, f"Disposable smoke sessions leaked into project: {remaining}"


def test_doctor_hooks_on_uninstalled_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test doctor_hooks on an uninstalled project: fails gracefully with informative instructions."""
    proj = tmp_path / "doctor_uninstalled_proj"
    proj.mkdir()

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1

    captured = capsys.readouterr()
    assert "AgentContract Codex Doctor Report" in captured.out
    assert "[FAIL] Project hooks file" in captured.out
    assert "hooks.json' not found" in captured.out
    assert "To install hooks locally:" in captured.out
    assert "agentcontract codex install --project" in captured.out


def test_doctor_hooks_via_cli_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test 'agentcontract codex doctor --project <dir>' CLI routing."""
    proj = tmp_path / "cli_doctor_proj"
    proj.mkdir()

    ret_inst = main(["codex", "install", "--project", str(proj)])
    assert ret_inst == 0

    ret_doc = main(["codex", "doctor", "--project", str(proj)])
    assert ret_doc == 0

    captured = capsys.readouterr()
    assert "AgentContract Codex Doctor Report" in captured.out
    assert "AgentContract Codex hooks are healthy, validated, and isolated" in captured.out


def test_doctor_hooks_preserves_foreign_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test that doctor_hooks recognizes and preserves foreign hook entries."""
    proj = tmp_path / "foreign_doc_proj"
    codex_dir = proj / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"

    foreign_cfg = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "node scripts/linter.js"}],
                }
            ]
        }
    }
    hooks_file.write_text(json.dumps(foreign_cfg, indent=2), encoding="utf-8")

    # Install merges AgentContract
    ret_install = install_hooks(project_dir=proj)
    assert ret_install == 0

    # Doctor verifies both AgentContract and foreign hooks
    ret_doc = doctor_hooks(project_dir=proj)
    assert ret_doc == 0

    captured = capsys.readouterr()
    assert "[PASS] Foreign configuration preserved (1 foreign handler(s))" in captured.out

    # Verify foreign command is still intact in file
    data = json.loads(hooks_file.read_text(encoding="utf-8"))
    commands = [
        h["command"]
        for entry in data["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
    ]
    assert "node scripts/linter.js" in commands


def test_zero_cross_project_interference_and_no_acl_mutations(tmp_path: Path) -> None:
    """Product usability & zero-interference regression test:
    Verify install, status, doctor, audit, uninstall cycles:
    - Never touch personal ~/.codex or global CODEX_HOME
    - Never configure elevated sandbox
    - Never invoke process kill or ACL mutations
    - Retain project boundary containment
    """
    import hashlib

    real_codex = Path.home() / ".codex"
    existed_before = real_codex.exists()
    entries_before = set(real_codex.iterdir()) if existed_before else set()

    def _hash_file(p: Path) -> str | None:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        except OSError:
            return None

    tracked = ["config.toml", "hooks.json", "auth.json"]
    hashes_before = {f: _hash_file(real_codex / f) for f in tracked} if existed_before else {}

    proj = tmp_path / "zero_interference_proj"
    proj.mkdir()

    # Run full lifecycle: install -> status -> doctor -> audit -> uninstall
    assert install_hooks(project_dir=proj) == 0
    assert status_hooks(project_dir=proj) == 0
    assert doctor_hooks(project_dir=proj) == 0
    assert audit_hooks(project_dir=proj) == 0
    assert uninstall_hooks(project_dir=proj) == 0

    # Assert real ~/.codex is completely identical
    if existed_before:
        assert real_codex.exists()
        entries_after = set(real_codex.iterdir())
        assert entries_after == entries_before, f"New entries added to ~/.codex: {entries_after - entries_before}"
        for f, pre_h in hashes_before.items():
            if pre_h is not None:
                assert _hash_file(real_codex / f) == pre_h, f"~/.codex/{f} was mutated!"
    else:
        assert not real_codex.exists(), "~/.codex was unexpectedly created!"


def test_doctor_hooks_rejects_wrapper_decoy_handler(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Round 10/11 regression: decoy handler like 'echo agentcontract.integrations.codex.hooks PreToolUse' must fail doctor."""
    proj = tmp_path / "decoy_proj"
    codex_dir = proj / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"

    decoy_cfg = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -m agentcontract.integrations.codex.hooks SessionStart",
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "echo agentcontract.integrations.codex.hooks PreToolUse",
                        }
                    ],
                }
            ],
        }
    }
    hooks_file.write_text(json.dumps(decoy_cfg, indent=2), encoding="utf-8")

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] Invalid AgentContract hook command registered under 'PreToolUse'" in captured.out
    assert "not a recognizable Python interpreter" in captured.out


def test_doctor_hooks_rejects_mismatched_event_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Round 10/11 regression: command with mismatched event argument under PreToolUse must fail doctor."""
    proj = tmp_path / "mismatched_proj"
    codex_dir = proj / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"

    mismatched_cfg = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -m agentcontract.integrations.codex.hooks SessionStart",
                        }
                    ]
                }
            ],
            "PreToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -m agentcontract.integrations.codex.hooks SessionStart",
                        }
                    ],
                }
            ],
        }
    }
    hooks_file.write_text(json.dumps(mismatched_cfg, indent=2), encoding="utf-8")

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] Invalid AgentContract hook command registered under 'PreToolUse'" in captured.out
    assert "Mismatched hook event argument" in captured.out


def test_doctor_hooks_fails_when_smoke_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 10/11 regression: cleanup failures during smoke session must be visible and fail doctor."""
    proj = tmp_path / "cleanup_fail_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_rmtree = shutil.rmtree

    def failing_rmtree(path, *args, **kwargs):
        raise PermissionError(f"Simulated access denied deleting {path}")

    monkeypatch.setattr(shutil, "rmtree", failing_rmtree)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] Smoke session cleanup failed" in captured.out
    assert "Smoke resources leaked on disk" in captured.out

    monkeypatch.undo()
    sessions_dir = proj / ".agentcontract" / "sessions"
    if sessions_dir.exists():
        real_rmtree(sessions_dir, ignore_errors=True)


def test_doctor_hooks_detects_user_codex_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 10/11 regression: any mutation to user ~/.codex during doctor run must be detected and fail."""
    mock_codex_home = tmp_path / "mock_user_codex"
    mock_codex_home.mkdir()
    (mock_codex_home / "config.toml").write_text("model = 'gpt-5'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(mock_codex_home))

    proj = tmp_path / "codex_mut_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_run = subprocess.run

    def mutating_run(*args, **kwargs):
        (mock_codex_home / "leaked_file.txt").write_text("leak", encoding="utf-8")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mutating_run)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] User global ~/.codex had new entries created" in captured.out


def test_doctor_hooks_rejects_allow_garbage_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 12 regression: PreToolUse ALLOW producing non-empty junk stdout must fail doctor."""
    proj = tmp_path / "allow_garbage_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_run = subprocess.run

    def fake_run(args, *pargs, **kwargs):
        stdin_data = kwargs.get("input", "")
        if "PreToolUse" in args and "call_smoke_allow" in stdin_data:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="some junk output from hook\n",
                stderr="",
            )
        return real_run(args, *pargs, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] PreToolUse ALLOW protocol violation" in captured.out
    assert "expected exit code 0 with completely empty stdout" in captured.out


def test_doctor_hooks_rejects_allow_structured_json_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 12 regression: PreToolUse ALLOW emitting non-empty structured ALLOW JSON must fail doctor."""
    proj = tmp_path / "allow_json_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_run = subprocess.run

    def fake_run(args, *pargs, **kwargs):
        stdin_data = kwargs.get("input", "")
        if "PreToolUse" in args and "call_smoke_allow" in stdin_data:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='{"hookSpecificOutput": {"permissionDecision": "allow"}}\n',
                stderr="",
            )
        return real_run(args, *pargs, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] PreToolUse ALLOW protocol violation" in captured.out
    assert "expected exit code 0 with completely empty stdout" in captured.out


def test_doctor_hooks_detects_user_codex_entry_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 12 regression: deletion of any top-level entry in ~/.codex during doctor run must fail doctor."""
    mock_codex_home = tmp_path / "mock_user_codex"
    mock_codex_home.mkdir()
    (mock_codex_home / "config.toml").write_text("model = 'gpt-5'\n", encoding="utf-8")
    (mock_codex_home / "preexisting_tool.txt").write_text("tool data", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(mock_codex_home))

    proj = tmp_path / "codex_del_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_run = subprocess.run

    def deleting_run(*args, **kwargs):
        (mock_codex_home / "preexisting_tool.txt").unlink(missing_ok=True)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", deleting_run)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] User global ~/.codex had entries deleted" in captured.out
    assert "preexisting_tool.txt" in captured.out


def test_doctor_hooks_detects_user_codex_tracked_file_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 12 regression: in-place modification of tracked config files in ~/.codex must fail doctor."""
    mock_codex_home = tmp_path / "mock_user_codex"
    mock_codex_home.mkdir()
    (mock_codex_home / "config.toml").write_text("model = 'gpt-5'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(mock_codex_home))

    proj = tmp_path / "codex_mod_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_run = subprocess.run

    def modifying_run(*args, **kwargs):
        (mock_codex_home / "config.toml").write_text("model = 'corrupted_model'\n", encoding="utf-8")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", modifying_run)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL] User global ~/.codex tracked config files were modified" in captured.out


def test_doctor_hooks_fails_on_user_codex_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 12 regression: unreadable tracked files in ~/.codex must fail doctor with an explicit error, never PASS."""
    mock_codex_home = tmp_path / "mock_user_codex"
    mock_codex_home.mkdir()
    cfg_file = mock_codex_home / "config.toml"
    cfg_file.write_text("model = 'gpt-5'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(mock_codex_home))

    proj = tmp_path / "codex_read_err_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_read_bytes = Path.read_bytes

    def failing_read_bytes(self, *args, **kwargs):
        if self.name == "config.toml" and str(mock_codex_home) in str(self):
            raise PermissionError("Simulated locked file")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", failing_read_bytes)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 1
    captured = capsys.readouterr()
    assert "[FAIL]" in captured.out
    assert "read error" in captured.out.lower() or "read failure" in captured.out.lower()


def test_doctor_hooks_untracked_file_mutation_does_not_falsely_claim_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 12 regression: mutating untracked files in ~/.codex does not cause doctor to claim all files were verified."""
    mock_codex_home = tmp_path / "mock_user_codex"
    mock_codex_home.mkdir()
    (mock_codex_home / "config.toml").write_text("model = 'gpt-5'\n", encoding="utf-8")
    (mock_codex_home / "untracked_cache.log").write_text("initial log\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(mock_codex_home))

    proj = tmp_path / "codex_untracked_proj"
    proj.mkdir()
    install_hooks(project_dir=proj)

    real_run = subprocess.run

    def mutating_untracked(*args, **kwargs):
        # Modify untracked log file content in-place without changing directory entries
        (mock_codex_home / "untracked_cache.log").write_text("new log line\n", encoding="utf-8")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", mutating_untracked)

    ret = doctor_hooks(project_dir=proj)
    assert ret == 0
    captured = capsys.readouterr()
    # Doctor must accurately scope its claim to tracked files and NOT claim untracked files were verified
    assert "tracked files ['config.toml'] verified unchanged" in captured.out
    assert "[NOT OBSERVED] External system ACLs, unmanaged background processes, untracked subdirectory contents" in captured.out




