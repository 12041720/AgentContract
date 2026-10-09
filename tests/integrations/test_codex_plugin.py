"""Tests for Codex plugin packaging, manifest compliance, and real hook discovery/installation."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest


def test_plugin_manifest_compliance() -> None:
    """Validate that plugin manifests adhere to the official nested extensions schema."""
    repo_root = Path(__file__).resolve().parents[2]
    plugin_dir = repo_root / "integrations" / "codex-plugin"

    manifest_path = plugin_dir / "plugin.json"
    compat_manifest_path = plugin_dir / ".codex-plugin" / "plugin.json"

    assert manifest_path.is_file(), f"Missing plugin manifest at {manifest_path}"
    assert compat_manifest_path.is_file(), f"Missing compatibility manifest at {compat_manifest_path}"

    for path in (manifest_path, compat_manifest_path):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("name") == "agentcontract"
        assert "extensions" in data

        # Official nested extensions format: extensions -> com.openai -> hooks
        assert "com.openai" in data["extensions"]
        openai_ext = data["extensions"]["com.openai"]
        assert isinstance(openai_ext, dict)
        assert "hooks" in openai_ext
        assert openai_ext["hooks"] == "./hooks/hooks.json"

        # Compatibility root-level hooks declaration
        assert data.get("hooks") == "./hooks/hooks.json"

        # Resolve relative path from manifest location
        hooks_rel = openai_ext["hooks"]
        manifest_parent = path.parent
        # For .codex-plugin/plugin.json, the plugin root is manifest_parent.parent
        plugin_root = manifest_parent if path == manifest_path else manifest_parent.parent
        resolved_hooks = (plugin_root / hooks_rel).resolve()
        assert resolved_hooks.is_file(), f"Referenced hooks file {resolved_hooks} does not exist"


def test_plugin_hooks_definition_and_lifecycle_events() -> None:
    """Validate all required lifecycle hook events are defined in hooks.json."""
    repo_root = Path(__file__).resolve().parents[2]
    hooks_file = repo_root / "integrations" / "codex-plugin" / "hooks" / "hooks.json"
    assert hooks_file.is_file()

    content = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert "hooks" in content
    hooks_map = content["hooks"]

    expected_events = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
    for ev in expected_events:
        assert ev in hooks_map, f"Missing lifecycle hook event {ev} in hooks.json"
        event_entries = hooks_map[ev]
        assert len(event_entries) >= 1
        sub_hooks = event_entries[0]["hooks"]
        assert len(sub_hooks) >= 1
        assert sub_hooks[0]["type"] == "command"
        assert "agentcontract.integrations.codex.hooks" in sub_hooks[0]["command"]


def test_real_codex_plugin_marketplace_discovery_and_install_smoke(tmp_path: Path) -> None:
    """Smoke test: execute real Codex CLI with an ISOLATED CODEX_HOME to verify marketplace & plugin discovery without touching user ~/.codex."""
    codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_bin:
        pytest.skip("Codex CLI executable not found on system PATH")

    repo_root = Path(__file__).resolve().parents[2]
    src_plugin = repo_root / "integrations" / "codex-plugin"

    # Set up isolated CODEX_HOME
    isolated_codex_home = tmp_path / "isolated_codex_home"
    isolated_codex_home.mkdir(parents=True, exist_ok=True)
    iso_env = dict(os.environ, CODEX_HOME=str(isolated_codex_home))

    # Pre-snapshot of real user's ~/.codex
    import hashlib
    def _hash_f(p: Path) -> str | None:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        except OSError:
            return None

    real_codex_home = Path.home() / ".codex"
    real_codex_pre_exists = real_codex_home.exists()
    real_codex_pre_entries = set(real_codex_home.iterdir()) if real_codex_pre_exists else set()
    tracked_files = ["config.toml", "hooks.json", "auth.json"]
    pre_hashes = {f: _hash_f(real_codex_home / f) for f in tracked_files} if real_codex_pre_exists else {}

    # Verify that CODEX_HOME isolation is honored by the Codex binary
    probe = subprocess.run(
        ["codex", "plugin", "marketplace", "list"],
        capture_output=True,
        text=True,
        shell=True,
        env=iso_env,
    )
    if probe.returncode != 0:
        pytest.skip(f"Codex CLI failed to start with isolated CODEX_HOME: {probe.stderr}")

    # Set up temporary marketplace structure inside tmp_path
    market_name = f"test_market_{abs(hash(str(tmp_path))) % 1000000}"
    agents_dir = tmp_path / ".agents" / "plugins"
    agents_dir.mkdir(parents=True)
    target_plugin_dir = tmp_path / "plugins" / "agentcontract"
    target_plugin_dir.mkdir(parents=True)
    target_codex_dir = target_plugin_dir / ".codex-plugin"
    target_codex_dir.mkdir(parents=True)
    target_hooks_dir = target_plugin_dir / "hooks"
    target_hooks_dir.mkdir(parents=True)

    # Copy files
    manifest_content = (src_plugin / "plugin.json").read_text(encoding="utf-8")
    (target_plugin_dir / "plugin.json").write_text(manifest_content, encoding="utf-8")
    (target_codex_dir / "plugin.json").write_text(manifest_content, encoding="utf-8")
    hooks_content = (src_plugin / "hooks" / "hooks.json").read_text(encoding="utf-8")
    (target_hooks_dir / "hooks.json").write_text(hooks_content, encoding="utf-8")

    marketplace_meta = {
        "name": market_name,
        "interface": {"displayName": "AgentContract Test Marketplace"},
        "plugins": [
            {
                "name": "agentcontract",
                "source": {
                    "source": "local",
                    "path": "./plugins/agentcontract",
                },
                "policy": {"installation": "AVAILABLE"},
            }
        ],
    }
    (agents_dir / "marketplace.json").write_text(json.dumps(marketplace_meta, indent=2), encoding="utf-8")

    try:
        # 1. Add marketplace via real Codex CLI into ISOLATED home
        add_market_res = subprocess.run(
            ["codex", "plugin", "marketplace", "add", str(tmp_path)],
            capture_output=True,
            text=True,
            shell=True,
            env=iso_env,
        )
        assert add_market_res.returncode == 0, f"codex plugin marketplace add failed: {add_market_res.stderr}"
        assert f"Added marketplace `{market_name}`" in add_market_res.stdout

        # 2. Verify marketplace is listed in ISOLATED home
        list_market_res = subprocess.run(
            ["codex", "plugin", "marketplace", "list"],
            capture_output=True,
            text=True,
            shell=True,
            env=iso_env,
        )
        assert list_market_res.returncode == 0
        assert market_name in list_market_res.stdout

        # 3. Install plugin from newly added marketplace into ISOLATED home
        install_res = subprocess.run(
            ["codex", "plugin", "add", f"agentcontract@{market_name}"],
            capture_output=True,
            text=True,
            shell=True,
            env=iso_env,
        )
        assert install_res.returncode == 0, f"codex plugin add failed: {install_res.stderr}"
        assert "Added plugin `agentcontract`" in install_res.stdout

        # 4. Verify plugin is recognized and installed in ISOLATED codex plugin list
        plugin_list_res = subprocess.run(
            ["codex", "plugin", "list"],
            capture_output=True,
            text=True,
            shell=True,
            env=iso_env,
        )
        assert plugin_list_res.returncode == 0
        matched_lines = [l for l in plugin_list_res.stdout.splitlines() if f"agentcontract@{market_name}" in l]
        assert len(matched_lines) == 1
        assert "installed" in matched_lines[0]
        assert "enabled" in matched_lines[0]

        # Verify artifacts were created strictly inside isolated_codex_home
        assert (isolated_codex_home / "plugins" / "cache" / market_name / "agentcontract").exists()

    finally:
        # 5. Clean up plugin and marketplace from ISOLATED home only
        subprocess.run(["codex", "plugin", "remove", "agentcontract"], capture_output=True, shell=True, env=iso_env)
        subprocess.run(["codex", "plugin", "marketplace", "remove", market_name], capture_output=True, shell=True, env=iso_env)

        # 6. Verify real user ~/.codex was NOT modified or polluted (guaranteed to execute even on test assertion failure)
        if real_codex_pre_exists:
            # Verify in-place mutations did not occur on tracked files
            for f, pre_h in pre_hashes.items():
                if pre_h is not None:
                    assert _hash_f(real_codex_home / f) == pre_h, f"real user {f} mutated in-place by plugin smoke test!"

            real_codex_post_entries = set(real_codex_home.iterdir())
            new_entries = real_codex_post_entries - real_codex_pre_entries
            # Ensure no test marketplace or plugin directories were written to real user home
            assert not any(market_name in p.name for p in new_entries)
            assert not (real_codex_home / "plugins" / "cache" / market_name).exists()
