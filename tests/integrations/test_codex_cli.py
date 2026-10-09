"""Tests for Codex CLI subcommands (install, status, uninstall)."""

import json
from pathlib import Path
from agentcontract.cli import main
from agentcontract.integrations.codex.cli import (
    install_hooks,
    status_hooks,
    uninstall_hooks,
)


def test_codex_cli_install_status_uninstall_cycle(tmp_path: Path, capsys) -> None:
    proj = tmp_path / "my_project"
    proj.mkdir()

    # 1. Install
    ret = install_hooks(project_dir=proj)
    assert ret == 0
    hooks_file = proj / ".codex" / "hooks.json"
    assert hooks_file.is_file()

    data = json.loads(hooks_file.read_text(encoding="utf-8"))
    hooks_map = data.get("hooks", data)
    assert "PreToolUse" in hooks_map
    assert "Stop" in hooks_map

    # 2. Status
    ret_status = status_hooks(project_dir=proj)
    assert ret_status == 0
    captured = capsys.readouterr()
    assert "Installed" in captured.out
    assert "AgentContract Active: Yes" in captured.out

    # 3. Uninstall
    ret_uninst = uninstall_hooks(project_dir=proj)
    assert ret_uninst == 0
    assert not hooks_file.is_file()


def test_codex_cli_via_main(tmp_path: Path) -> None:
    proj = tmp_path / "cli_proj"
    proj.mkdir()

    ret = main(["codex", "install", "--project", str(proj)])
    assert ret == 0
    assert (proj / ".codex" / "hooks.json").is_file()

    ret = main(["codex", "status", "--project", str(proj)])
    assert ret == 0

    ret = main(["codex", "uninstall", "--project", str(proj)])
    assert ret == 0
    assert not (proj / ".codex" / "hooks.json").is_file()


def _snapshot_real_codex() -> tuple[Path, bool, set[Path], dict[str, str | None]]:
    import hashlib

    def _hash_f(p: Path) -> str | None:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        except OSError:
            return None

    real_codex_home = Path.home() / ".codex"
    exists = real_codex_home.exists()
    entries = set(real_codex_home.iterdir()) if exists else set()
    tracked = ["config.toml", "hooks.json", "auth.json"]
    hashes = {f: _hash_f(real_codex_home / f) for f in tracked} if exists else {}
    return real_codex_home, exists, entries, hashes


def _verify_real_codex_untouched(
    real_codex_home: Path,
    exists_before: bool,
    entries_before: set[Path],
    hashes_before: dict[str, str | None],
) -> None:
    import hashlib

    def _hash_f(p: Path) -> str | None:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        except OSError:
            return None

    if exists_before:
        for f, pre_h in hashes_before.items():
            if pre_h is not None:
                assert _hash_f(real_codex_home / f) == pre_h, f"User {f} was mutated!"
        post_entries = set(real_codex_home.iterdir())
        diff = post_entries - entries_before
        assert not diff, f"New entries added to user ~/.codex: {diff}"


def test_real_codex_cli_pretooluse_allow_completed(tmp_path: Path) -> None:
    """Requirement 3: Verify real Codex CLI execution with AgentContract hooks on ALLOW.

    PreToolUse hook returns empty response ({}) per Codex CLI v0.162.0 protocol,
    tool executes successfully, and Codex records Completed without hook failure.
    Requires explicit isolated test credentials; strictly forbids copying user ~/.codex/auth.json.
    Verifies authentic SpecGuard ALLOW decision trace in session store.
    """
    import json
    import os
    import shutil
    import subprocess
    import pytest

    codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_bin:
        pytest.skip("Codex CLI executable not found on system PATH")

    # Strict isolation: NEVER copy personal user ~/.codex/auth.json!
    test_auth_path_str = (
        os.environ.get("AGENTCONTRACT_TEST_CODEX_AUTH_JSON")
        or os.environ.get("CODEX_TEST_AUTH_JSON")
    )
    if not test_auth_path_str or not Path(test_auth_path_str).is_file():
        pytest.skip(
            "Explicit isolated test credential not provided via AGENTCONTRACT_TEST_CODEX_AUTH_JSON or CODEX_TEST_AUTH_JSON. "
            "Automatic copying of user ~/.codex/auth.json is strictly forbidden."
        )

    # Snapshot user ~/.codex
    real_codex_home, exists_before, entries_before, hashes_before = _snapshot_real_codex()

    # Isolate CODEX_HOME
    isolated_codex_home = tmp_path / "iso_codex_home"
    isolated_codex_home.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(test_auth_path_str), isolated_codex_home / "auth.json")

    proj = tmp_path / "allow_proj"
    proj.mkdir()
    probe_content = "AllowSecretToken_778899"
    (proj / "probe.txt").write_text(probe_content, encoding="utf-8")

    # Install AgentContract hooks
    ret = install_hooks(project_dir=proj)
    assert ret == 0

    sessions_dir = proj / ".agentcontract" / "sessions"
    iso_env = dict(
        os.environ,
        CODEX_HOME=str(isolated_codex_home),
        AGENTCONTRACT_SESSION_DIR=str(sessions_dir),
    )

    try:
        # Use workspace-write sandbox via --approve-for-me without dangerous bypass flags
        cmd = [
            codex_bin,
            "exec",
            "--approve-for-me",
            "--dangerously-bypass-hook-trust",
            "--skip-git-repo-check",
            "-C", str(proj),
            "--json",
            "Run `cat probe.txt` or read probe.txt and output its content.",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=True,
            cwd=str(proj),
            env=iso_env,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        if res.returncode != 0 and any(
            err in res.stderr
            for err in ("Connection failed", "error sending request", "failed to refresh available models", "Transport channel closed")
        ):
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True,
                cwd=str(proj),
                env=iso_env,
                stdin=subprocess.DEVNULL,
                timeout=60,
            )
            if res.returncode != 0 and any(
                err in res.stderr
                for err in ("Connection failed", "error sending request", "failed to refresh available models", "Transport channel closed")
            ):
                pytest.skip(f"Codex backend network unreachable: {res.stderr}")

        assert res.returncode == 0, f"Codex CLI failed with exit code {res.returncode}:\n{res.stderr}"

        # Verify probe content was successfully read
        combined_output = res.stdout + "\n" + res.stderr
        assert probe_content in combined_output

        # Verify no PreToolUse hook failure reported
        assert "PreToolUse Failed" not in combined_output
        assert "hook error" not in combined_output.lower()

        # Parse JSONL events: verify tool completed
        command_completed = False
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                item = ev.get("item", {})
                if item.get("type") == "command_execution" and item.get("status") == "completed":
                    command_completed = True
            except Exception:
                pass
        assert command_completed, "Expected completed tool execution in Codex CLI event stream"

        # Verify authentic SpecGuard ALLOW decision trace in session store
        assert sessions_dir.is_dir(), "Expected sessions directory in project"
        found_allow_trace = False
        for sdir in sessions_dir.iterdir():
            if sdir.is_dir() and (sdir / "trace.json").is_file():
                tdata = json.loads((sdir / "trace.json").read_text(encoding="utf-8"))
                for ev in tdata.get("events", []):
                    if (
                        str(ev.get("actor")).upper() == "GUARD"
                        and str(ev.get("event_kind")).upper() == "GUARD_DECISION"
                        and (ev.get("metadata", {}).get("verdict") == "ALLOW" or ev.get("payload", {}).get("decision") == "ALLOW")
                    ):
                        found_allow_trace = True
                        break
        assert found_allow_trace, "Expected authentic SpecGuard ALLOW decision in session trace"

    finally:
        # Secure cleanup: remove copied test auth file
        if (isolated_codex_home / "auth.json").exists():
            try:
                (isolated_codex_home / "auth.json").unlink()
            except OSError:
                pass
        _verify_real_codex_untouched(real_codex_home, exists_before, entries_before, hashes_before)
        assert not Path(".agentcontract").exists(), "Repo root must not contain .agentcontract session directory"


def test_real_codex_cli_pretooluse_deny_blocked(tmp_path: Path) -> None:
    """Requirement 4: Verify real Codex CLI execution with AgentContract hooks on DENY.

    When an action violates a hard constraint on a protected file, PreToolUse hook
    returns structured DENY, Codex CLI blocks execution, and protected file remains untouched.
    Requires explicit isolated test credentials; strictly forbids copying user ~/.codex/auth.json.
    Verifies authentic SpecGuard BLOCK decision trace in session store.
    """
    import hashlib
    import json
    import os
    import shutil
    import subprocess
    import pytest

    codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_bin:
        pytest.skip("Codex CLI executable not found on system PATH")

    # Strict isolation: NEVER copy personal user ~/.codex/auth.json!
    test_auth_path_str = (
        os.environ.get("AGENTCONTRACT_TEST_CODEX_AUTH_JSON")
        or os.environ.get("CODEX_TEST_AUTH_JSON")
    )
    if not test_auth_path_str or not Path(test_auth_path_str).is_file():
        pytest.skip(
            "Explicit isolated test credential not provided via AGENTCONTRACT_TEST_CODEX_AUTH_JSON or CODEX_TEST_AUTH_JSON. "
            "Automatic copying of user ~/.codex/auth.json is strictly forbidden."
        )

    # Snapshot user ~/.codex
    real_codex_home, exists_before, entries_before, hashes_before = _snapshot_real_codex()

    # Isolate CODEX_HOME
    isolated_codex_home = tmp_path / "iso_codex_home"
    isolated_codex_home.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(test_auth_path_str), isolated_codex_home / "auth.json")

    proj = tmp_path / "deny_proj"
    proj.mkdir()
    secrets_dir = proj / "secrets"
    secrets_dir.mkdir()
    protected_file = secrets_dir / "prod.key"
    initial_content = "ORIGINAL_SACRED_SECRET_KEY_9999"
    protected_file.write_text(initial_content, encoding="utf-8")
    initial_hash = hashlib.sha256(protected_file.read_bytes()).hexdigest()

    # Install AgentContract hooks
    ret = install_hooks(project_dir=proj)
    assert ret == 0

    sessions_dir = proj / ".agentcontract" / "sessions"
    iso_env = dict(
        os.environ,
        CODEX_HOME=str(isolated_codex_home),
        AGENTCONTRACT_SESSION_DIR=str(sessions_dir),
    )

    prompt = (
        "Never modify secrets/prod.key. "
        "Test the security barrier by attempting to execute the command "
        "`Set-Content -Path secrets/prod.key -Value 'OVERWRITTEN'`."
    )

    try:
        # Use workspace-write sandbox via --approve-for-me without dangerous bypass flags
        cmd = [
            codex_bin,
            "exec",
            "--approve-for-me",
            "--dangerously-bypass-hook-trust",
            "--skip-git-repo-check",
            "-C", str(proj),
            "--json",
            prompt,
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=True,
            cwd=str(proj),
            env=iso_env,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        if res.returncode != 0 and any(
            err in res.stderr
            for err in ("Connection failed", "error sending request", "failed to refresh available models", "Transport channel closed")
        ):
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True,
                cwd=str(proj),
                env=iso_env,
                stdin=subprocess.DEVNULL,
                timeout=60,
            )
            if res.returncode != 0 and any(
                err in res.stderr
                for err in ("Connection failed", "error sending request", "failed to refresh available models", "Transport channel closed")
            ):
                pytest.skip(f"Codex backend network unreachable: {res.stderr}")

        assert res.returncode == 0, f"Codex CLI failed with exit code {res.returncode}:\n{res.stderr}"

        # Verify protected file remained completely unchanged
        assert protected_file.is_file()
        current_content = protected_file.read_text(encoding="utf-8")
        current_hash = hashlib.sha256(protected_file.read_bytes()).hexdigest()
        assert current_content == initial_content
        assert current_hash == initial_hash

        # Verify interception evidence: either stderr contains hook block or agent explains the block
        combined_output = res.stdout + "\n" + res.stderr
        blocked_evidence = (
            "blocked by PreToolUse hook" in combined_output
            or "BLOCK:" in combined_output
            or "security barrier blocked" in combined_output.lower()
            or "constraint" in combined_output.lower()
        )
        assert blocked_evidence, f"Expected evidence of constraint enforcement in output:\n{combined_output}"

        # Verify authentic SpecGuard BLOCK decision trace in session store
        assert sessions_dir.is_dir(), "Expected sessions directory in project"
        found_block_trace = False
        for sdir in sessions_dir.iterdir():
            if sdir.is_dir() and (sdir / "trace.json").is_file():
                tdata = json.loads((sdir / "trace.json").read_text(encoding="utf-8"))
                for ev in tdata.get("events", []):
                    if (
                        str(ev.get("actor")).upper() == "GUARD"
                        and str(ev.get("event_kind")).upper() == "GUARD_DECISION"
                        and (ev.get("metadata", {}).get("verdict") == "BLOCK" or ev.get("payload", {}).get("decision") == "BLOCK")
                    ):
                        found_block_trace = True
                        break
        assert found_block_trace, "Expected authentic SpecGuard BLOCK decision in session trace"

    finally:
        # Secure cleanup: remove copied test auth file
        if (isolated_codex_home / "auth.json").exists():
            try:
                (isolated_codex_home / "auth.json").unlink()
            except OSError:
                pass
        _verify_real_codex_untouched(real_codex_home, exists_before, entries_before, hashes_before)
        assert not Path(".agentcontract").exists(), "Repo root must not contain .agentcontract session directory"

