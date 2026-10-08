"""Tests for Codex plugin packaging, manifest compliance, and hook discovery."""

import json
from pathlib import Path


def test_plugin_manifest_compliance() -> None:
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
        assert "com.openai.hooks" in data["extensions"]
        assert data["extensions"]["com.openai.hooks"] == "./hooks/hooks.json"
        assert data.get("hooks") == "./hooks/hooks.json"

        # Resolve relative path from manifest location
        hooks_rel = data["extensions"]["com.openai.hooks"]
        manifest_parent = path.parent
        # For .codex-plugin/plugin.json, the plugin root is manifest_parent.parent
        plugin_root = manifest_parent if path == manifest_path else manifest_parent.parent
        resolved_hooks = (plugin_root / hooks_rel).resolve()
        assert resolved_hooks.is_file(), f"Referenced hooks file {resolved_hooks} does not exist"


def test_plugin_hooks_definition_and_lifecycle_events() -> None:
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


def test_plugin_discovery_and_resolution(tmp_path: Path) -> None:
    # Simulate Codex discovering plugins in .codex/plugins/<plugin_name>
    repo_root = Path(__file__).resolve().parents[2]
    src_plugin = repo_root / "integrations" / "codex-plugin"

    # Create workspace with plugin installed in .codex/plugins/agentcontract
    ws_plugin_dir = tmp_path / ".codex" / "plugins" / "agentcontract"
    ws_plugin_dir.mkdir(parents=True)

    # Copy manifest and hooks
    (ws_plugin_dir / "plugin.json").write_text(
        (src_plugin / "plugin.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    ws_hooks_dir = ws_plugin_dir / "hooks"
    ws_hooks_dir.mkdir(parents=True)
    (ws_hooks_dir / "hooks.json").write_text(
        (src_plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Emulate Codex plugin discovery engine
    discovered_plugins = []
    plugins_root = tmp_path / ".codex" / "plugins"
    for item in plugins_root.iterdir():
        if item.is_dir() and (item / "plugin.json").is_file():
            manifest = json.loads((item / "plugin.json").read_text(encoding="utf-8"))
            hooks_ref = (
                manifest.get("extensions", {}).get("com.openai.hooks")
                or manifest.get("hooks")
            )
            if hooks_ref:
                target_hooks = (item / hooks_ref).resolve()
                if target_hooks.is_file():
                    hooks_data = json.loads(target_hooks.read_text(encoding="utf-8"))
                    discovered_plugins.append({
                        "name": manifest.get("name"),
                        "plugin_dir": item,
                        "hooks_file": target_hooks,
                        "hooks": hooks_data.get("hooks", {}),
                    })

    assert len(discovered_plugins) == 1
    plugin = discovered_plugins[0]
    assert plugin["name"] == "agentcontract"
    assert "PreToolUse" in plugin["hooks"]
    assert "Stop" in plugin["hooks"]
