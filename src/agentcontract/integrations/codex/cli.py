"""CLI management commands for Codex lifecycle hooks."""

import copy
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

from agentcontract.integrations.codex.state import CodexSessionStore

HOOKS_TEMPLATE: dict[str, Any] = {
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python -m agentcontract.integrations.codex.hooks SessionStart"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python -m agentcontract.integrations.codex.hooks UserPromptSubmit"
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
            "command": "python -m agentcontract.integrations.codex.hooks PreToolUse"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python -m agentcontract.integrations.codex.hooks PostToolUse"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python -m agentcontract.integrations.codex.hooks Stop"
          }
        ]
      }
    ]
  }
}

AGENTCONTRACT_HOOK_MARKER = "agentcontract.integrations.codex.hooks"


def _is_agentcontract_hook_entry(entry: Any) -> bool:
    """Check if a hook entry belongs to AgentContract."""
    if not isinstance(entry, dict):
        return False
    sub_hooks = entry.get("hooks", [])
    if isinstance(sub_hooks, list):
        for h in sub_hooks:
            if isinstance(h, dict) and AGENTCONTRACT_HOOK_MARKER in h.get("command", ""):
                return True
    return False


def _atomic_write_json(file_path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON data to file to prevent corruption or partial writes."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.parent / f".tmp_{file_path.name}_{uuid.uuid4().hex}"
    try:
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp_path), str(file_path))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def install_hooks(project_dir: str | Path = ".") -> int:
    """Install AgentContract lifecycle hooks into the target project's .codex directory."""
    proj = Path(project_dir).resolve()
    # Guard against ambiguous or dangerous root targets
    if proj == proj.anchor or str(proj) == str(Path.home()):
        sys.stderr.write(
            f"Error: Refusing to install hooks at system root or user home directory ({proj}). "
            "AgentContract hooks must be scoped to a specific project directory.\n"
        )
        return 1

    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    if hooks_file.is_file():
        # Validate existing JSON before touching
        try:
            content = hooks_file.read_text(encoding="utf-8")
            existing = json.loads(content)
        except Exception as err:
            sys.stderr.write(
                f"Error: Existing hooks file at {hooks_file} contains invalid JSON ({err}). "
                "Refusing to overwrite to prevent data loss.\n"
            )
            return 1

        if not isinstance(existing, dict):
            sys.stderr.write(
                f"Error: Existing hooks file at {hooks_file} is not a JSON object. "
                "Refusing to overwrite to prevent data loss.\n"
            )
            return 1

        # Determine if hooks map is wrapped under "hooks" key or top-level
        if "hooks" in existing and isinstance(existing["hooks"], dict):
            hooks_map = existing["hooks"]
        else:
            if any(ev in existing for ev in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")):
                hooks_map = existing
            else:
                existing["hooks"] = {}
                hooks_map = existing["hooks"]

        modified = False
        template_hooks = HOOKS_TEMPLATE["hooks"]

        for event, template_entries in template_hooks.items():
            current_entries = hooks_map.setdefault(event, [])
            if not isinstance(current_entries, list):
                current_entries = []
                hooks_map[event] = current_entries

            # Check if AgentContract entry is already present in this event
            has_ac = any(_is_agentcontract_hook_entry(e) for e in current_entries)
            if not has_ac:
                # Merge template entries without altering existing foreign entries
                current_entries.extend(copy.deepcopy(template_entries))
                modified = True

        if not modified:
            print(f"AgentContract hooks are already installed and up to date in {hooks_file}")
            return 0

        _atomic_write_json(hooks_file, existing)
        print(f"Successfully merged AgentContract hooks into {hooks_file}")
        return 0

    # New file creation
    codex_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(hooks_file, copy.deepcopy(HOOKS_TEMPLATE))
    print(f"Successfully installed AgentContract hooks to {hooks_file}")
    return 0


def status_hooks(project_dir: str | Path = ".") -> int:
    """Report status of AgentContract hooks and persisted sessions in the target project."""
    proj = Path(project_dir).resolve()
    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    print("AgentContract Codex Harness Status:")
    print(f"  Project Root: {proj}")
    print("  Scope Boundary: Project-local only (zero effect on global ~/.codex)")

    if hooks_file.is_file():
        try:
            content = hooks_file.read_text(encoding="utf-8")
            data = json.loads(content)
            hooks_map = data.get("hooks", data) if isinstance(data, dict) else {}

            ac_entries = 0
            foreign_entries = 0
            configured_events = []

            for event, entries in hooks_map.items():
                if isinstance(entries, list):
                    configured_events.append(event)
                    for e in entries:
                        if _is_agentcontract_hook_entry(e):
                            ac_entries += 1
                        else:
                            foreign_entries += 1

            print(f"  Hooks Configuration: Installed ({hooks_file})")
            print(f"  AgentContract Active: {'Yes' if ac_entries > 0 else 'No'} ({ac_entries} entry/entries)")
            print(f"  Foreign Hooks Preserved: {foreign_entries} foreign entry/entries")
            print(f"  Configured Events: {', '.join(configured_events)}")
        except Exception as err:
            print(f"  Hooks Configuration: Corrupted file ({err})")
    else:
        print(f"  Hooks Configuration: Not installed ({hooks_file} does not exist)")

    # Session store status
    store = CodexSessionStore(base_dir=proj / ".agentcontract" / "sessions")
    sessions = store.list_sessions()
    print(f"  Active Session Store: {store.base_dir}")
    print(f"  Total Persisted Sessions: {len(sessions)}")
    for s in sessions[:5]:
        sid = s.get("session_id", "unknown")
        tid = s.get("trace_id", "unknown")
        print(f"    - Session: {sid} (Trace: {tid})")
    if len(sessions) > 5:
        print(f"    ... and {len(sessions) - 5} more")

    return 0


def uninstall_hooks(project_dir: str | Path = ".") -> int:
    """Uninstall AgentContract lifecycle hooks from the target project."""
    proj = Path(project_dir).resolve()
    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    if not hooks_file.is_file():
        print(f"No hooks file found at {hooks_file}")
        return 0

    try:
        content = hooks_file.read_text(encoding="utf-8")
        existing = json.loads(content)
    except Exception as err:
        sys.stderr.write(
            f"Error: Hooks file at {hooks_file} contains invalid JSON ({err}). "
            "Refusing to modify to prevent data loss.\n"
        )
        return 1

    if not isinstance(existing, dict):
        sys.stderr.write(
            f"Error: Hooks file at {hooks_file} is not a JSON object. "
            "Refusing to modify to prevent data loss.\n"
        )
        return 1

    hooks_map = existing.get("hooks", existing) if "hooks" in existing and isinstance(existing["hooks"], dict) else existing

    removed_count = 0
    remaining_events = {}

    for event, entries in list(hooks_map.items()):
        if isinstance(entries, list):
            new_entries = [e for e in entries if not _is_agentcontract_hook_entry(e)]
            removed_count += (len(entries) - len(new_entries))
            if new_entries:
                remaining_events[event] = new_entries
        else:
            remaining_events[event] = entries

    if removed_count == 0:
        print(f"No AgentContract hooks found in {hooks_file}; leaving untouched.")
        return 0

    # If foreign hooks remain, preserve them
    if remaining_events:
        if "hooks" in existing and isinstance(existing["hooks"], dict):
            existing["hooks"] = remaining_events
        else:
            existing = remaining_events
        _atomic_write_json(hooks_file, existing)
        print(f"Removed {removed_count} AgentContract hook entry/entries from {hooks_file} (preserved remaining project hooks)")
    else:
        # File contained only AgentContract hooks
        hooks_file.unlink(missing_ok=True)
        print(f"Removed AgentContract hooks from {hooks_file}")
        try:
            if codex_dir.exists() and not any(codex_dir.iterdir()):
                codex_dir.rmdir()
        except OSError:
            pass

    return 0


def audit_hooks(project_dir: str | Path = ".") -> int:
    """Non-destructive diagnostic audit of Codex configuration isolation."""
    proj = Path(project_dir).resolve()
    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"
    user_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

    print("AgentContract Codex Isolation Audit Report:")
    print("=" * 60)
    print(f"Target Project: {proj}")

    # 1. Project-local check
    if hooks_file.is_file():
        try:
            data = json.loads(hooks_file.read_text(encoding="utf-8"))
            hooks_map = data.get("hooks", data) if isinstance(data, dict) else {}
            ac_found = any(
                _is_agentcontract_hook_entry(e)
                for entries in hooks_map.values()
                if isinstance(entries, list)
                for e in entries
            )
            print(f"  Project Hooks File: {hooks_file} (Present, AgentContract: {'Yes' if ac_found else 'No'})")
        except Exception as err:
            print(f"  Project Hooks File: {hooks_file} (Corrupted JSON: {err})")
    else:
        print(f"  Project Hooks File: {hooks_file} (Not Present)")

    # 2. Read-only User Global Codex Home check
    print(f"\nUser Codex Home: {user_codex_home}")
    if not user_codex_home.exists():
        print("  Status: User Codex home does not exist.")
        print("  Zero External Side Effects: Confirmed.")
        return 0

    global_hooks = user_codex_home / "hooks.json"
    has_global_ac_hooks = False
    if global_hooks.is_file():
        try:
            gh_content = global_hooks.read_text(encoding="utf-8")
            has_global_ac_hooks = AGENTCONTRACT_HOOK_MARKER in gh_content
            print(f"  Global hooks.json: Present (Contains AgentContract: {'YES - Warning' if has_global_ac_hooks else 'No'})")
        except Exception:
            print(f"  Global hooks.json: Present (Unparseable)")
    else:
        print(f"  Global hooks.json: Not Present (Clean)")

    # Check for residual plugin cache or marketplace registrations
    plugin_cache_dir = user_codex_home / "plugins" / "cache"
    has_global_plugin = False
    if plugin_cache_dir.is_dir():
        try:
            for mkt in plugin_cache_dir.iterdir():
                if (mkt / "agentcontract").exists():
                    has_global_plugin = True
                    break
        except Exception:
            pass

    print(f"  Global Plugins Cache: {'Contains AgentContract registration' if has_global_plugin else 'Clean (No AgentContract plugin)'}")

    # 3. Assessment & Guidance
    print("\nIsolation Assessment:")
    if not has_global_ac_hooks and not has_global_plugin:
        print("  [PASSED] Zero External Side Effects Confirmed.")
        print("  AgentContract is strictly project-scoped and does not affect other Codex workspaces or Desktop.")
    else:
        print("  [NOTICE] Residual global AgentContract registrations detected in user's Codex home.")
        print("  To surgically remove global plugin registrations without affecting other plugins, run:")
        if has_global_plugin:
            print("    codex plugin remove agentcontract")
        if has_global_ac_hooks:
            print(f"    (Manually remove AgentContract entries from {global_hooks})")
        print("  Note: AgentContract never automatically modifies or deletes global configurations.")

    print("=" * 60)
    return 0
