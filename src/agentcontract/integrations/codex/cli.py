"""CLI management commands for Codex lifecycle hooks."""

import json
from pathlib import Path
import shutil
import sys
from typing import Any

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


def install_hooks(project_dir: str | Path = ".") -> int:
    """Install AgentContract lifecycle hooks into the target project's .codex directory."""
    proj = Path(project_dir).resolve()
    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    codex_dir.mkdir(parents=True, exist_ok=True)

    if hooks_file.is_file():
        # Check if already installed
        try:
            existing = json.loads(hooks_file.read_text(encoding="utf-8"))
            if "agentcontract" in json.dumps(existing):
                print(f"AgentContract hooks are already installed in {hooks_file}")
                return 0
        except Exception:
            pass

        # Backup existing hooks file
        backup_file = codex_dir / "hooks.json.bak"
        shutil.copy2(hooks_file, backup_file)
        print(f"Existing hooks file backed up to {backup_file}")

    # Write new hooks configuration
    hooks_file.write_text(json.dumps(HOOKS_TEMPLATE, indent=2), encoding="utf-8")
    print(f"Successfully installed AgentContract hooks to {hooks_file}")
    return 0


def status_hooks(project_dir: str | Path = ".") -> int:
    """Report status of AgentContract hooks and persisted sessions in the target project."""
    proj = Path(project_dir).resolve()
    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    print("AgentContract Codex Harness Status:")
    print(f"  Project Root: {proj}")

    if hooks_file.is_file():
        try:
            content = hooks_file.read_text(encoding="utf-8")
            data = json.loads(content)
            has_ac = "agentcontract" in content
            hooks_map = data.get("hooks", data) if isinstance(data, dict) else {}
            events = [k for k in hooks_map.keys() if isinstance(hooks_map[k], list)]
            print(f"  Hooks Configuration: Installed ({hooks_file})")
            print(f"  AgentContract Active: {'Yes' if has_ac else 'No'}")
            print(f"  Configured Events: {', '.join(events)}")
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
    backup_file = codex_dir / "hooks.json.bak"

    if not hooks_file.is_file():
        print(f"No hooks file found at {hooks_file}")
        return 0

    try:
        content = hooks_file.read_text(encoding="utf-8")
        if "agentcontract" not in content:
            print(f"Hooks file at {hooks_file} does not appear to be AgentContract hooks; leaving untouched.")
            return 0
    except Exception:
        pass

    if backup_file.is_file():
        shutil.move(str(backup_file), str(hooks_file))
        print(f"Restored previous hooks configuration from {backup_file}")
    else:
        hooks_file.unlink()
        print(f"Removed AgentContract hooks from {hooks_file}")

    return 0
