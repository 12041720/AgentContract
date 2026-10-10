"""CLI management commands for Codex lifecycle hooks."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tomllib
from typing import Any
import uuid

from agentcontract.integrations.codex.state import CodexSessionStore

LIFECYCLE_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")

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
LIFECYCLE_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


def _is_forbidden_target_dir(target_dir: Path) -> bool:
    """Check if target directory is filesystem root or user home directory."""
    try:
        resolved = target_dir.resolve()
        # Typed check for filesystem root (e.g. C:\ or /)
        if resolved == Path(resolved.anchor) or resolved.parent == resolved:
            return True
        # Case-normalized check for user home directory
        home = Path.home().resolve()
        if os.path.normcase(str(resolved)) == os.path.normcase(str(home)):
            return True
    except Exception:
        pass
    return False


def _get_forbidden_codex_homes() -> list[Path]:
    """Return canonical paths of user's global Codex home directories."""
    homes = []
    try:
        homes.append((Path.home() / ".codex").resolve())
    except Exception:
        pass
    env_codex = os.environ.get("CODEX_HOME")
    if env_codex:
        try:
            homes.append(Path(env_codex).resolve())
        except Exception:
            pass
    return homes


def _validate_project_contained_path(target_path: Path, project_root: Path) -> tuple[bool, str]:
    """Validate that target_path is strictly contained within canonical project_root.
    
    Rejects symlinks, directory junctions, and reparse points that escape project_root
    or resolve to forbidden directories (system roots, user home, global CODEX_HOME).
    """
    try:
        proj_canonical = project_root.resolve()
    except Exception as err:
        return False, f"Failed to resolve project root '{project_root}': {err}"

    if _is_forbidden_target_dir(proj_canonical):
        return False, f"Project root '{proj_canonical}' is a system root or user home directory."

    # Traverse from target_path up to project root, validating any existing components
    curr = target_path
    visited_components = []
    while True:
        visited_components.append(curr)
        if curr == proj_canonical or curr.parent == curr:
            break
        curr = curr.parent

    for comp in reversed(visited_components):
        is_link = False
        try:
            if comp.is_symlink() or (hasattr(comp, "is_junction") and comp.is_junction()):
                is_link = True
        except Exception:
            pass

        if comp.exists() or is_link:
            try:
                resolved_comp = comp.resolve()
            except Exception as err:
                return False, f"Path component '{comp}' cannot be safely resolved ({err})."

            try:
                if not resolved_comp.is_relative_to(proj_canonical):
                    return False, (
                        f"Path component '{comp}' escapes project root boundary "
                        f"(resolves to '{resolved_comp}')."
                    )
            except (ValueError, AttributeError):
                return False, (
                    f"Path component '{comp}' escapes project root boundary "
                    f"(resolves to '{resolved_comp}')."
                )

            if _is_forbidden_target_dir(resolved_comp):
                return False, f"Path component '{comp}' resolves to forbidden directory '{resolved_comp}'."

            for forbidden_home in _get_forbidden_codex_homes():
                try:
                    if resolved_comp == forbidden_home or resolved_comp.is_relative_to(forbidden_home):
                        return False, (
                            f"Path component '{comp}' resolves to global Codex home '{resolved_comp}'."
                        )
                except (ValueError, Exception):
                    pass

    # Final check on target_path canonical destination
    try:
        resolved_target = target_path.resolve()
        if not resolved_target.is_relative_to(proj_canonical):
            return False, f"Path '{target_path}' escapes project root boundary (resolves to '{resolved_target}')."
        if _is_forbidden_target_dir(resolved_target):
            return False, f"Path '{target_path}' resolves to forbidden directory '{resolved_target}'."
        if _is_forbidden_target_dir(resolved_target.parent):
            return False, f"Parent of '{target_path}' resolves to forbidden directory '{resolved_target.parent}'."
        for forbidden_home in _get_forbidden_codex_homes():
            try:
                if resolved_target == forbidden_home or resolved_target.is_relative_to(forbidden_home):
                    return False, f"Path '{target_path}' resolves to global Codex home '{resolved_target}'."
            except (ValueError, Exception):
                pass
    except Exception as err:
        return False, f"Failed to verify destination path '{target_path}': {err}"

    return True, ""


def _is_agentcontract_handler(handler: Any) -> bool:
    """Check if an individual hook handler dict belongs to AgentContract."""
    if isinstance(handler, dict):
        cmd = handler.get("command", "")
        if isinstance(cmd, str) and AGENTCONTRACT_HOOK_MARKER in cmd:
            return True
    return False


def _is_agentcontract_hook_entry(entry: Any) -> bool:
    """Check if an entire entry or group contains any AgentContract handlers."""
    if not isinstance(entry, dict):
        return False
    sub_hooks = entry.get("hooks", [])
    if isinstance(sub_hooks, list):
        for h in sub_hooks:
            if _is_agentcontract_handler(h):
                return True
    elif _is_agentcontract_handler(entry):
        return True
    return False


def _validate_agentcontract_command(command: str, expected_event: str | None = None) -> tuple[bool, str]:
    """Strictly validate that a registered hook command correctly targets the AgentContract handler.

    Rejects wrapper decoys (e.g. echo, cat), broken syntax, missing -m flag, or mismatched event arguments.
    """
    if not isinstance(command, str) or not command.strip():
        return False, "Hook command is empty or not a string."

    try:
        tokens = shlex.split(command, posix=False)
    except Exception as err:
        return False, f"Failed to parse hook command with shlex: {err}"

    if len(tokens) < 3:
        return False, f"Hook command has too few arguments ({len(tokens)}): '{command}'"

    # 1. Executable check: must be a Python interpreter
    exe_path = tokens[0].strip("\"'")
    exe_name = Path(exe_path).name.lower()
    exe_base = exe_name[:-4] if exe_name.endswith(".exe") else exe_name
    valid_pythons = {"python", "python3", "python3.12", "python3.11", "py"}
    if exe_base not in valid_pythons and not exe_base.startswith("python"):
        return False, f"Command executable '{tokens[0]}' is not a recognizable Python interpreter (expected 'python' or 'python3')."

    # 2. Module check: must invoke -m agentcontract.integrations.codex.hooks
    if "-m" not in tokens:
        return False, "Command does not invoke AgentContract hooks via '-m' flag."
    m_idx = tokens.index("-m")
    if m_idx + 1 >= len(tokens):
        return False, "Missing module name after '-m' flag."
    mod_name = tokens[m_idx + 1]
    if mod_name != AGENTCONTRACT_HOOK_MARKER:
        return False, f"Command invokes unexpected module '{mod_name}' instead of '{AGENTCONTRACT_HOOK_MARKER}'."

    # 3. Event argument check
    if expected_event is not None:
        if m_idx + 2 >= len(tokens):
            return False, f"Missing event argument in command (expected '{expected_event}')."
        event_arg = tokens[m_idx + 2]
        if event_arg.lower() != expected_event.lower():
            return False, f"Mismatched hook event argument: command specifies '{event_arg}', expected '{expected_event}'."

    return True, ""


def _extract_agentcontract_commands(hooks_map: dict[str, Any]) -> dict[str, list[str]]:
    """Extract all AgentContract hook command strings grouped by event name."""
    result: dict[str, list[str]] = {ev: [] for ev in LIFECYCLE_EVENTS}
    for event, entries in hooks_map.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                if "hooks" in entry and isinstance(entry["hooks"], list):
                    for h in entry["hooks"]:
                        if isinstance(h, dict) and _is_agentcontract_handler(h):
                            cmd = h.get("command", "")
                            if isinstance(cmd, str):
                                result.setdefault(event, []).append(cmd)
                elif _is_agentcontract_handler(entry):
                    cmd = entry.get("command", "")
                    if isinstance(cmd, str):
                        result.setdefault(event, []).append(cmd)
    return result



def _validate_hooks_json_structure(data: Any, file_path: Path) -> tuple[bool, str]:
    """Strictly validate the schema/shape of an existing hooks.json file.
    
    Rejects malformed hooks maps, malformed event arrays, and malformed handlers.
    """
    if not isinstance(data, dict):
        return False, f"Existing hooks file at {file_path} is not a JSON object."

    if "hooks" in data:
        hooks_val = data["hooks"]
        if not isinstance(hooks_val, dict):
            return False, f"Top-level 'hooks' key in {file_path} must be a dictionary, got {type(hooks_val).__name__}."
        hooks_map = hooks_val
    else:
        if not data:
            # Empty dict is valid empty config
            return True, ""
        # If top-level has keys, verify they are event names
        if all(k in LIFECYCLE_EVENTS for k in data.keys()):
            hooks_map = data
        else:
            return False, f"Hooks file at {file_path} lacks a valid top-level 'hooks' object."

    for event_name, event_val in hooks_map.items():
        if not isinstance(event_val, list):
            return False, f"Event '{event_name}' in {file_path} must be a list of hook entries, got {type(event_val).__name__}."
        for idx, entry in enumerate(event_val):
            if not isinstance(entry, dict):
                return False, f"Entry #{idx} under event '{event_name}' in {file_path} must be a dictionary."
            if "hooks" in entry:
                sub_hooks = entry["hooks"]
                if not isinstance(sub_hooks, list):
                    return False, f"'hooks' list in entry #{idx} under event '{event_name}' in {file_path} must be a list."
                for h_idx, handler in enumerate(sub_hooks):
                    if not isinstance(handler, dict):
                        return False, f"Handler #{h_idx} in entry #{idx} under event '{event_name}' in {file_path} must be a dictionary."

    return True, ""


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
    if _is_forbidden_target_dir(proj):
        sys.stderr.write(
            f"Error: Refusing to install hooks at system root or user home directory ({proj}). "
            "AgentContract hooks must be scoped to a specific project directory.\n"
        )
        return 1

    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    # Validate that neither .codex nor hooks.json escapes project root via symlink/junction
    ok_dir, reason_dir = _validate_project_contained_path(codex_dir, proj)
    if not ok_dir:
        sys.stderr.write(f"Error: Refusing to install hooks: {reason_dir}\n")
        return 1

    ok_file, reason_file = _validate_project_contained_path(hooks_file, proj)
    if not ok_file:
        sys.stderr.write(f"Error: Refusing to install hooks: {reason_file}\n")
        return 1

    if hooks_file.is_file():
        # Validate existing JSON syntax
        try:
            content = hooks_file.read_text(encoding="utf-8")
            existing = json.loads(content)
        except Exception as err:
            sys.stderr.write(
                f"Error: Existing hooks file at {hooks_file} contains invalid JSON ({err}). "
                "Refusing to overwrite to prevent data loss.\n"
            )
            return 1

        # Validate existing JSON structure strictly
        is_valid, validation_err = _validate_hooks_json_structure(existing, hooks_file)
        if not is_valid:
            sys.stderr.write(
                f"Error: Malformed hook structure in {hooks_file}: {validation_err}. "
                "Refusing to overwrite to prevent data loss.\n"
            )
            return 1

        # Determine target hooks_map
        if "hooks" in existing and isinstance(existing["hooks"], dict):
            hooks_map = existing["hooks"]
        else:
            if existing:
                hooks_map = existing
            else:
                existing["hooks"] = {}
                hooks_map = existing["hooks"]

        modified = False
        template_hooks = HOOKS_TEMPLATE["hooks"]

        for event, template_entries in template_hooks.items():
            current_entries = hooks_map.setdefault(event, [])

            # Check if AgentContract is already present in this event
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
    if _is_forbidden_target_dir(proj):
        sys.stderr.write(
            f"Error: Refusing to query status at system root or user home directory ({proj}).\n"
        )
        return 1

    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    ok_dir, reason_dir = _validate_project_contained_path(codex_dir, proj)
    if not ok_dir:
        sys.stderr.write(f"Error: Refusing to query status: {reason_dir}\n")
        return 1

    ok_file, reason_file = _validate_project_contained_path(hooks_file, proj)
    if not ok_file:
        sys.stderr.write(f"Error: Refusing to query status: {reason_file}\n")
        return 1

    print("AgentContract Codex Harness Status:")
    print(f"  Project Root: {proj}")
    print("  Scope Boundary: Project-local only (.codex and .agentcontract within project root)")

    if hooks_file.is_file():
        try:
            content = hooks_file.read_text(encoding="utf-8")
            data = json.loads(content)
            is_valid, validation_err = _validate_hooks_json_structure(data, hooks_file)
            if not is_valid:
                print(f"  Hooks Configuration: Malformed file ({validation_err})")
            else:
                hooks_map = data.get("hooks", data) if isinstance(data, dict) else {}
                ac_handlers = 0
                foreign_handlers = 0
                configured_events = []

                for event, entries in hooks_map.items():
                    if isinstance(entries, list):
                        configured_events.append(event)
                        for e in entries:
                            if isinstance(e, dict) and "hooks" in e and isinstance(e["hooks"], list):
                                for h in e["hooks"]:
                                    if _is_agentcontract_handler(h):
                                        ac_handlers += 1
                                    else:
                                        foreign_handlers += 1
                            elif _is_agentcontract_handler(e):
                                ac_handlers += 1
                            else:
                                foreign_handlers += 1

                print(f"  Hooks Configuration: Installed ({hooks_file})")
                print(f"  AgentContract Active: {'Yes' if ac_handlers > 0 else 'No'} ({ac_handlers} handler(s))")
                print(f"  Foreign Handlers Preserved: {foreign_handlers} foreign handler(s)")
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
    if _is_forbidden_target_dir(proj):
        sys.stderr.write(
            f"Error: Refusing to uninstall hooks at system root or user home directory ({proj}).\n"
        )
        return 1

    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    ok_dir, reason_dir = _validate_project_contained_path(codex_dir, proj)
    if not ok_dir:
        sys.stderr.write(f"Error: Refusing to uninstall hooks: {reason_dir}\n")
        return 1

    ok_file, reason_file = _validate_project_contained_path(hooks_file, proj)
    if not ok_file:
        sys.stderr.write(f"Error: Refusing to uninstall hooks: {reason_file}\n")
        return 1

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

    is_valid, validation_err = _validate_hooks_json_structure(existing, hooks_file)
    if not is_valid:
        sys.stderr.write(
            f"Error: Malformed hook structure in {hooks_file}: {validation_err}. "
            "Refusing to modify to prevent data loss.\n"
        )
        return 1

    is_wrapped = "hooks" in existing and isinstance(existing["hooks"], dict)
    hooks_map = existing["hooks"] if is_wrapped else existing
    unrelated_top_level_keys = set(existing.keys()) - {"hooks"} if is_wrapped else set()

    removed_handlers_count = 0
    events_to_delete = []

    for event, entries in list(hooks_map.items()):
        if not isinstance(entries, list):
            continue

        event_had_ac = False
        new_entries = []

        for entry in entries:
            if isinstance(entry, dict) and "hooks" in entry and isinstance(entry["hooks"], list):
                kept_handlers = []
                for h in entry["hooks"]:
                    if _is_agentcontract_handler(h):
                        removed_handlers_count += 1
                        event_had_ac = True
                    else:
                        kept_handlers.append(h)

                if kept_handlers:
                    entry["hooks"] = kept_handlers
                    new_entries.append(entry)
                else:
                    extra_keys = set(entry.keys()) - {"hooks", "matcher"}
                    if extra_keys:
                        entry["hooks"] = []
                        new_entries.append(entry)
                    else:
                        pass
            elif _is_agentcontract_handler(entry):
                removed_handlers_count += 1
                event_had_ac = True
            else:
                new_entries.append(entry)

        if event_had_ac:
            if new_entries:
                hooks_map[event] = new_entries
            else:
                events_to_delete.append(event)
        else:
            # Foreign event (e.g. PostToolUse: [] or third-party hooks) preserved as is
            hooks_map[event] = new_entries

    for event in events_to_delete:
        del hooks_map[event]

    if removed_handlers_count == 0:
        print(f"No AgentContract hooks found in {hooks_file}; leaving untouched.")
        return 0

    # Delete file only if it was entirely AgentContract-generated and has no unrelated content
    if not unrelated_top_level_keys and not hooks_map:
        hooks_file.unlink(missing_ok=True)
        print(f"Removed AgentContract hooks from {hooks_file}")
        try:
            if codex_dir.exists() and not any(codex_dir.iterdir()):
                codex_dir.rmdir()
        except OSError:
            pass
        return 0

    # Foreign configuration or metadata remains: preserve structurally valid config
    _atomic_write_json(hooks_file, existing)
    print(f"Removed {removed_handlers_count} AgentContract handler(s) from {hooks_file} (preserved foreign configuration)")
    return 0


def _inspect_codex_config_toml(config_path: Path) -> tuple[str, list[str]]:
    """Inspect Codex config.toml safely with tomllib for AgentContract residual entries.
    
    Returns:
        (status, list_of_residual_items)
        where status is 'CLEAN', 'RESIDUAL', or 'UNVERIFIED/INCOMPLETE'
    """
    if not config_path.is_file():
        return "CLEAN", []

    try:
        content = config_path.read_bytes()
        config_data = tomllib.loads(content.decode("utf-8", errors="replace"))
    except Exception as err:
        return "UNVERIFIED/INCOMPLETE", [f"Error reading/parsing config.toml: {err}"]

    residual_items = []

    # Check [plugins] table
    plugins_table = config_data.get("plugins")
    if isinstance(plugins_table, dict):
        for plugin_name, plugin_cfg in plugins_table.items():
            if "agentcontract" in plugin_name.lower():
                residual_items.append(f'plugins."{plugin_name}"')

    # Check [marketplaces] table
    marketplaces_table = config_data.get("marketplaces")
    if isinstance(marketplaces_table, dict):
        for mkt_name in marketplaces_table.keys():
            if "agentcontract" in mkt_name.lower() or "test_ac_market" in mkt_name.lower():
                residual_items.append(f'marketplaces."{mkt_name}"')

    # General key search in top-level
    for k in config_data.keys():
        if "agentcontract" in k.lower() and k not in ("plugins", "marketplaces"):
            residual_items.append(f'config key "{k}"')

    if residual_items:
        return "RESIDUAL", residual_items
    return "CLEAN", []


def audit_hooks(project_dir: str | Path = ".") -> int:
    """Non-destructive diagnostic audit of Codex configuration isolation."""
    proj = Path(project_dir).resolve()
    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"
    user_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

    print("AgentContract Codex Isolation Audit Report:")
    print("=" * 60)
    print(f"Target Project: {proj}")

    # 1. Project-local check & boundary containment
    ok_dir, reason_dir = _validate_project_contained_path(codex_dir, proj)
    ok_file, reason_file = _validate_project_contained_path(hooks_file, proj)
    has_project_escape = not ok_dir or not ok_file

    if has_project_escape:
        escape_reason = reason_dir if not ok_dir else reason_file
        print(f"  Project Hooks Directory: [SUSPICIOUS / ESCAPE DETECTED] ({escape_reason})")
    elif hooks_file.is_file():
        try:
            data = json.loads(hooks_file.read_text(encoding="utf-8"))
            is_valid, validation_err = _validate_hooks_json_structure(data, hooks_file)
            if not is_valid:
                print(f"  Project Hooks File: {hooks_file} (Malformed: {validation_err})")
            else:
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
        print("  Status: User Codex home directory does not exist.")
        print("\nInspection Coverage:")
        print(f"  Inspected Sources: Project root ({proj}); Global Codex home directory not present.")
        print("  Coverage Note: Desktop GUI state, system runtime memory, and uninspected external paths remain UNVERIFIED.")
        print("\nIsolation Assessment:")
        if has_project_escape:
            print("  [ESCAPE_DETECTED] Project-local .codex directory escapes project root boundary.")
        else:
            print("  [PROJECT_SCOPED_ONLY] No global Codex configuration directory exists.")
        print("=" * 60)
        return 0

    # 2a. Inspect global config.toml
    config_path = user_codex_home / "config.toml"
    config_status, config_residuals = _inspect_codex_config_toml(config_path)
    if config_path.is_file():
        if config_status == "RESIDUAL":
            print(f"  Global config.toml: Present (Contains residual entries: {', '.join(config_residuals)})")
        elif config_status == "UNVERIFIED/INCOMPLETE":
            print(f"  Global config.toml: Present ({config_residuals[0]})")
        else:
            print("  Global config.toml: Present (Clean, no AgentContract entries)")
    else:
        print("  Global config.toml: Not Present (Clean)")

    # 2b. Inspect global hooks.json
    global_hooks = user_codex_home / "hooks.json"
    has_global_ac_hooks = False
    global_hooks_unparseable = False
    if global_hooks.is_file():
        try:
            gh_content = global_hooks.read_text(encoding="utf-8")
            has_global_ac_hooks = AGENTCONTRACT_HOOK_MARKER in gh_content
            print(f"  Global hooks.json: Present (Contains AgentContract: {'YES - Warning' if has_global_ac_hooks else 'No'})")
        except Exception:
            global_hooks_unparseable = True
            print("  Global hooks.json: Present (Unparseable)")
    else:
        print("  Global hooks.json: Not Present (Clean)")

    # 2c. Inspect global plugin cache
    plugin_cache_dir = user_codex_home / "plugins" / "cache"
    has_global_plugin = False
    cached_marketplaces = []
    if plugin_cache_dir.is_dir():
        try:
            for mkt in plugin_cache_dir.iterdir():
                if (mkt / "agentcontract").exists():
                    has_global_plugin = True
                    cached_marketplaces.append(mkt.name)
        except Exception:
            pass

    print(f"  Global Plugins Cache: {'Contains AgentContract registration (' + ', '.join(cached_marketplaces) + ')' if has_global_plugin else 'Clean (No AgentContract plugin)'}")

    # 3. Inspection Coverage Summary
    print("\nInspection Coverage:")
    inspected_items = [f"Project ({proj})"]
    if config_path.is_file():
        inspected_items.append("config.toml")
    if global_hooks.is_file():
        inspected_items.append("hooks.json")
    if plugin_cache_dir.is_dir():
        inspected_items.append("plugins/cache")
    print(f"  Inspected Sources: {', '.join(inspected_items)}")
    print("  Coverage Note: Desktop GUI state, system runtime memory, and uninspected external paths remain UNVERIFIED.")

    # 4. Assessment & Guidance
    print("\nIsolation Assessment:")
    is_residual = (config_status == "RESIDUAL" or has_global_ac_hooks or has_global_plugin)
    is_unverified = (config_status == "UNVERIFIED/INCOMPLETE" or global_hooks_unparseable)

    if has_project_escape:
        print("  [ESCAPE_DETECTED] Project-local .codex configuration escapes project root boundary.")
    elif is_residual:
        print("  [RESIDUAL] Residual global AgentContract registrations detected in user's Codex home.")
        print("  Guidance for targeted, non-destructive cleanup:")
        if has_global_plugin:
            print("    - Active cached plugin detected. To remove via Codex CLI:")
            print("        codex plugin remove agentcontract")
        if config_status == "RESIDUAL" and not has_global_plugin:
            print(f"    - Stale configuration entries detected in {config_path} without active cached plugin.")
            print("      To remove safely: create a backup of config.toml and remove only the specific section(s):")
            for item in config_residuals:
                print(f"        * Remove [{item}]")
        if has_global_ac_hooks:
            print(f"    - AgentContract hooks detected in {global_hooks}.")
            print("      To remove safely: create a backup of hooks.json and remove only AgentContract command handlers.")
        print("  Note: AgentContract never automatically modifies or deletes global configurations.")
    elif is_unverified:
        print("  [UNVERIFIED/INCOMPLETE] Unable to verify full global isolation status due to unreadable config files.")
    else:
        print("  [PROJECT_SCOPED_ONLY] No known AgentContract entries found in inspected global sources.")
        print("  Notice: Static inspection is limited to file-based CLI configuration; Desktop GUI state remains UNVERIFIED.")

    print("=" * 60)
    return 0


def doctor_hooks(project_dir: str | Path = ".") -> int:
    """Run comprehensive offline diagnostics and smoke test for Codex lifecycle integration.

    Validates:
      1. Boundary containment (no escape to system roots, user home, or global CODEX_HOME).
      2. Project hooks configuration (.codex/hooks.json validity, AgentContract presence, foreign preservation).
      3. Offline hook execution smoke test (SessionStart, PreToolUse ALLOW, PreToolUse BLOCK).
      4. SpecGuard decision evaluation and authentic trace logging.
      5. Runtime enforcement wire-format compliance (ALLOW -> empty / non-deny; BLOCK -> structured deny).
      6. Zero-interference isolation verification (no ~/.codex mutation, no process kill, no ACL change).

    Returns:
      0 if all diagnostic checks pass cleanly.
      1 if any check fails or hooks are not installed.
    """
    proj = Path(project_dir).resolve()
    if _is_forbidden_target_dir(proj):
        sys.stderr.write(
            f"Error: Refusing to run doctor at system root or user home directory ({proj}).\n"
        )
        return 1

    codex_dir = proj / ".codex"
    hooks_file = codex_dir / "hooks.json"

    ok_dir, reason_dir = _validate_project_contained_path(codex_dir, proj)
    if not ok_dir:
        sys.stderr.write(f"Error: Refusing to run doctor: {reason_dir}\n")
        return 1

    ok_file, reason_file = _validate_project_contained_path(hooks_file, proj)
    if not ok_file:
        sys.stderr.write(f"Error: Refusing to run doctor: {reason_file}\n")
        return 1

    print("AgentContract Codex Doctor Report")
    print("=" * 60)
    print(f"Target Project: {proj}")

    # 1. Check if hooks are installed
    if not hooks_file.is_file():
        print("\n1. Configuration & Containment:")
        print(f"  [FAIL] Project hooks file '{hooks_file}' not found.")
        print("  AgentContract hooks are not installed in this project.")
        print("\nTo install hooks locally:")
        print(f"  agentcontract codex install --project {proj}")
        print("=" * 60)
        return 1

    try:
        content = hooks_file.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as err:
        print("\n1. Configuration & Containment:")
        print(f"  [FAIL] Unable to read/parse hooks.json: {err}")
        print("=" * 60)
        return 1

    is_valid, validation_err = _validate_hooks_json_structure(data, hooks_file)
    if not is_valid:
        print("\n1. Configuration & Containment:")
        print(f"  [FAIL] hooks.json structure is invalid: {validation_err}")
        print("=" * 60)
        return 1

    hooks_map = data.get("hooks", data) if isinstance(data, dict) else {}
    ac_handlers = 0
    foreign_handlers = 0
    for event, entries in hooks_map.items():
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and "hooks" in e and isinstance(e["hooks"], list):
                    for h in e["hooks"]:
                        if _is_agentcontract_handler(h):
                            ac_handlers += 1
                        else:
                            foreign_handlers += 1
                elif _is_agentcontract_handler(e):
                    ac_handlers += 1
                else:
                    foreign_handlers += 1

    if ac_handlers == 0:
        print("\n1. Configuration & Containment:")
        print(f"  [FAIL] No AgentContract handlers registered in {hooks_file}")
        print("=" * 60)
        return 1

    # Extract and validate all registered AgentContract commands
    ac_cmds = _extract_agentcontract_commands(hooks_map)
    for event_name, cmds in ac_cmds.items():
        for cmd in cmds:
            ok_cmd, cmd_err = _validate_agentcontract_command(cmd, expected_event=event_name)
            if not ok_cmd:
                print("\n1. Configuration & Containment:")
                print(f"  [FAIL] Invalid AgentContract hook command registered under '{event_name}': '{cmd}' ({cmd_err})")
                print("=" * 60)
                return 1

    # Require registered commands for SessionStart and PreToolUse
    if not ac_cmds.get("SessionStart"):
        print("\n1. Configuration & Containment:")
        print("  [FAIL] Missing required AgentContract handler for 'SessionStart'")
        print("=" * 60)
        return 1
    if not ac_cmds.get("PreToolUse"):
        print("\n1. Configuration & Containment:")
        print("  [FAIL] Missing required AgentContract handler for 'PreToolUse'")
        print("=" * 60)
        return 1

    session_start_cmd = ac_cmds["SessionStart"][0]
    pre_tool_cmd = ac_cmds["PreToolUse"][0]

    print("\n1. Configuration & Containment:")
    print("  [PASS] Project boundary containment verified (.codex strictly within project root)")
    print(f"  [PASS] hooks.json syntax, schema, and command handlers valid ({ac_handlers} AgentContract handler(s))")
    if foreign_handlers > 0:
        print(f"  [PASS] Foreign configuration preserved ({foreign_handlers} foreign handler(s))")
    else:
        print("  [PASS] Clean project-only hook configuration (no foreign handlers)")

    # Snapshot user global ~/.codex before smoke test to detect any leaks or mutations
    user_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    user_codex_existed_before = user_codex_home.exists()
    user_codex_entries_before: set[str] = set()
    user_codex_hashes_before: dict[str, str] = {}
    baseline_read_errors: list[str] = []

    TRACKED_GLOBAL_FILES = ("config.toml", "hooks.json", "auth.json")

    if user_codex_existed_before:
        try:
            user_codex_entries_before = {p.name for p in user_codex_home.iterdir()}
        except Exception as err:
            baseline_read_errors.append(f"Failed to list entries in user Codex home: {err}")

        for f_name in TRACKED_GLOBAL_FILES:
            target_f = user_codex_home / f_name
            if target_f.is_file():
                try:
                    user_codex_hashes_before[f_name] = hashlib.sha256(target_f.read_bytes()).hexdigest()
                except Exception as err:
                    baseline_read_errors.append(f"Failed to read/hash tracked file '{f_name}': {err}")

    if baseline_read_errors:
        print("\n5. Isolation & Environment Integrity:")
        print("  [FAIL] Baseline snapshot of user global ~/.codex failed due to read error:")
        for r_err in baseline_read_errors:
            print(f"    - {r_err}")
        print("=" * 60)
        return 1

    # 2. Offline Smoke Test (SessionStart, PreToolUse ALLOW, PreToolUse BLOCK)
    from agentcontract.constraints.models import (
        Constraint,
        ConstraintProvenance,
        ConstraintScope,
        ConstraintSource,
        ConstraintStrength,
        RuleEffect,
    )

    smoke_session_id = f"smoke_{uuid.uuid4().hex[:12]}"
    sessions_dir = proj / ".agentcontract" / "sessions"
    smoke_store = CodexSessionStore(base_dir=sessions_dir)
    smoke_session_dir = sessions_dir / smoke_session_id
    smoke_lock_file = sessions_dir / f"{smoke_session_id}.lock"

    child_env = os.environ.copy()
    child_env["AGENTCONTRACT_SESSION_DIR"] = str(sessions_dir)
    # Ensure local agentcontract package is resolvable by child python
    repo_src = str(Path(__file__).resolve().parents[3] / "src")
    existing_pp = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = f"{repo_src}{os.pathsep}{existing_pp}" if existing_pp else repo_src

    smoke_failed = False
    cleanup_errors: list[str] = []

    try:
        # 2a. Execute registered SessionStart command via child subprocess
        start_payload = {
            "session_id": smoke_session_id,
            "cwd": str(proj),
            "hook_event_name": "SessionStart",
        }
        res_start = subprocess.run(
            shlex.split(session_start_cmd, posix=False),
            input=json.dumps(start_payload),
            text=True,
            capture_output=True,
            env=child_env,
            cwd=str(proj),
            timeout=15,
        )
        if res_start.returncode != 0:
            print(f"\n2. Offline Hook Subprocess Execution Smoke Test:\n  [FAIL] SessionStart subprocess failed with exit code {res_start.returncode}:\n{res_start.stderr}")
            print("=" * 60)
            smoke_failed = True
            return 1

        # 2b. Inject deterministic test constraint into session ledger in parent process
        with smoke_store.session_transaction(smoke_session_id) as tx:
            smoke_rule = Constraint(
                id="doctor_smoke_rule",
                name="protect_secrets_prod_key",
                description="Never modify protected secrets file 'secrets/prod.key'.",
                strength=ConstraintStrength.HARD,
                rule_effect=RuleEffect.DENY,
                provenance=ConstraintProvenance(
                    source=ConstraintSource.POLICY,
                    source_text="Doctor diagnostic smoke rule",
                    author="AgentContractDoctor",
                ),
                scope=ConstraintScope(
                    target_type="filesystem",
                    paths=("secrets/prod.key",),
                    actions=("FILE_WRITE", "FILE_DELETE", "COMMAND_EXEC", "apply_patch"),
                ),
            )
            tx.ledger.add(smoke_rule)

        # 2c. Execute registered PreToolUse command via subprocess for ALLOW (harmless read)
        allow_payload = {
            "session_id": smoke_session_id,
            "cwd": str(proj),
            "tool_name": "Bash",
            "tool_use_id": "call_smoke_allow",
            "tool_input": {"command": "Get-Content probe.txt"},
            "hook_event_name": "PreToolUse",
        }
        res_allow = subprocess.run(
            shlex.split(pre_tool_cmd, posix=False),
            input=json.dumps(allow_payload),
            text=True,
            capture_output=True,
            env=child_env,
            cwd=str(proj),
            timeout=15,
        )
        if res_allow.returncode != 0:
            print(f"\n3. SpecGuard Decision Evaluation:\n  [FAIL] PreToolUse ALLOW evaluation failed with non-zero exit code ({res_allow.returncode}): stderr='{res_allow.stderr}'")
            print("=" * 60)
            smoke_failed = True
            return 1

        if res_allow.stdout.strip() != "":
            print(
                "\n3. SpecGuard Decision Evaluation:\n"
                f"  [FAIL] PreToolUse ALLOW protocol violation: expected exit code 0 with completely empty stdout (no input rewrite), "
                f"but received nonempty stdout: {res_allow.stdout.strip()!r}"
            )
            print("=" * 60)
            smoke_failed = True
            return 1

        # 2d. Execute registered PreToolUse command via subprocess for BLOCK (forbidden write)
        block_payload = {
            "session_id": smoke_session_id,
            "cwd": str(proj),
            "tool_name": "Bash",
            "tool_use_id": "call_smoke_block",
            "tool_input": {"command": "Set-Content -Path secrets/prod.key -Value 'test'"},
            "hook_event_name": "PreToolUse",
        }
        res_block = subprocess.run(
            shlex.split(pre_tool_cmd, posix=False),
            input=json.dumps(block_payload),
            text=True,
            capture_output=True,
            env=child_env,
            cwd=str(proj),
            timeout=15,
        )
        block_json: dict[str, Any] = {}
        if res_block.stdout.strip():
            try:
                block_json = json.loads(res_block.stdout.strip())
            except Exception:
                block_json = {}

        is_block = (
            res_block.returncode == 0
            and block_json.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        )
        if not is_block:
            print(f"\n3. SpecGuard Decision Evaluation:\n  [FAIL] PreToolUse BLOCK evaluation failed: stdout='{res_block.stdout}', stderr='{res_block.stderr}'")
            print("=" * 60)
            smoke_failed = True
            return 1

        # 2e. Verify session trace file generated on disk
        trace_file = smoke_session_dir / "trace.json"
        if not trace_file.is_file():
            print("\n3. SpecGuard Decision Evaluation:\n  [FAIL] Session trace file was not generated.")
            print("=" * 60)
            smoke_failed = True
            return 1

        trace_data = json.loads(trace_file.read_text(encoding="utf-8"))
        trace_events = trace_data.get("events", [])
        has_guard_allow = any(
            str(e.get("actor")).upper() == "GUARD"
            and str(e.get("event_kind")).upper() == "GUARD_DECISION"
            and (e.get("metadata", {}).get("verdict") == "ALLOW" or e.get("payload", {}).get("decision") == "ALLOW")
            for e in trace_events
        )
        has_guard_block = any(
            str(e.get("actor")).upper() == "GUARD"
            and str(e.get("event_kind")).upper() == "GUARD_DECISION"
            and (e.get("metadata", {}).get("verdict") == "BLOCK" or e.get("payload", {}).get("decision") == "BLOCK")
            for e in trace_events
        )
        if not has_guard_allow or not has_guard_block:
            print(
                f"\n3. SpecGuard Decision Evaluation:\n  [FAIL] Guard trace verification failed "
                f"(allow={has_guard_allow}, block={has_guard_block})"
            )
            print("=" * 60)
            smoke_failed = True
            return 1

    except Exception as smoke_exc:
        smoke_failed = True
        print(f"\n2. Offline Hook Execution Smoke Test:\n  [FAIL] Unexpected exception during smoke test: {smoke_exc}")
        print("=" * 60)
        return 1

    finally:
        # Clean up disposable smoke session directory and lock file completely
        # Make any cleanup failures visible!
        if smoke_session_dir.exists():
            try:
                shutil.rmtree(smoke_session_dir)
            except Exception as err:
                cleanup_errors.append(f"Failed to remove smoke session directory '{smoke_session_dir}': {err}")
            if smoke_session_dir.exists():
                cleanup_errors.append(f"Smoke session directory '{smoke_session_dir}' still exists after deletion attempt.")

        if smoke_lock_file.exists():
            try:
                smoke_lock_file.unlink(missing_ok=True)
            except Exception as err:
                cleanup_errors.append(f"Failed to remove smoke lock file '{smoke_lock_file}': {err}")
            if smoke_lock_file.exists():
                cleanup_errors.append(f"Smoke lock file '{smoke_lock_file}' still exists after deletion attempt.")

        try:
            if sessions_dir.exists() and not any(sessions_dir.iterdir()):
                sessions_dir.rmdir()
                ac_dir = proj / ".agentcontract"
                if ac_dir.exists() and not any(ac_dir.iterdir()):
                    ac_dir.rmdir()
        except OSError:
            pass

    if smoke_failed:
        return 1

    if cleanup_errors:
        print("\nDisposable Smoke Session Cleanup:")
        print("  [FAIL] Smoke session cleanup failed:")
        for err_msg in cleanup_errors:
            print(f"    - {err_msg}")
        print("  Smoke resources leaked on disk.")
        print("=" * 60)
        return 1

    print("\n2. Offline Hook Execution Smoke Test:")
    print("  [PASS] SessionStart hook executed successfully via subprocess")
    print("  [PASS] PreToolUse hook invoked and processed inputs via subprocess")

    print("\n3. SpecGuard Decision Evaluation:")
    print("  [PASS] Compliant action evaluated -> SpecGuard ALLOW recorded")
    print("  [PASS] Forbidden action evaluated -> SpecGuard BLOCK recorded")
    print("  [PASS] Authentic trace events recorded in session store")

    print("\n4. Runtime Enforcement Wire-Format:")
    print("  [PASS] ALLOW wire-format: exit code 0 with completely empty stdout (no input rewrite)")
    print("  [PASS] BLOCK wire-format: structured JSON denial (permissionDecision=deny)")

    # 5. Isolation & Environment Integrity Verification
    print("\n5. Isolation & Environment Integrity:")
    codex_mutated = False
    if not user_codex_existed_before:
        if user_codex_home.exists():
            print("  [FAIL] User global ~/.codex was created unexpectedly during doctor run!")
            codex_mutated = True
        else:
            print("  [PASS] User global ~/.codex observed untouched (directory did not exist before/after)")
    else:
        if not user_codex_home.exists():
            print("  [FAIL] User global ~/.codex was deleted during doctor run!")
            codex_mutated = True
        else:
            try:
                post_entries = {p.name for p in user_codex_home.iterdir()}
            except Exception as err:
                print(f"  [FAIL] Failed to list entries in user global ~/.codex after smoke test: {err}")
                codex_mutated = True
                post_entries = set()

            if not codex_mutated:
                added_entries = post_entries - user_codex_entries_before
                deleted_entries = user_codex_entries_before - post_entries
                if added_entries or deleted_entries:
                    if added_entries:
                        print(f"  [FAIL] User global ~/.codex had new entries created: {sorted(added_entries)}")
                    if deleted_entries:
                        print(f"  [FAIL] User global ~/.codex had entries deleted: {sorted(deleted_entries)}")
                    codex_mutated = True
                else:
                    mutated_files = []
                    post_read_errors = []
                    for f_name, pre_h in user_codex_hashes_before.items():
                        target_f = user_codex_home / f_name
                        if not target_f.is_file():
                            mutated_files.append(f"{f_name} (deleted or changed file type)")
                        else:
                            try:
                                curr_h = hashlib.sha256(target_f.read_bytes()).hexdigest()
                                if curr_h != pre_h:
                                    mutated_files.append(f"{f_name} (content modified)")
                            except Exception as err:
                                post_read_errors.append(f"Failed to read/hash tracked file '{f_name}': {err}")

                    if post_read_errors:
                        print("  [FAIL] Post-smoke verification of user global ~/.codex failed due to read error:")
                        for p_err in post_read_errors:
                            print(f"    - {p_err}")
                        codex_mutated = True
                    elif mutated_files:
                        print(f"  [FAIL] User global ~/.codex tracked config files were modified: {mutated_files}")
                        codex_mutated = True
                    else:
                        tracked_list = sorted(user_codex_hashes_before.keys())
                        print(f"  [PASS] User global ~/.codex observed untouched (top-level entries identical; tracked files {tracked_list} verified unchanged)")

    if codex_mutated:
        print("=" * 60)
        return 1

    print("  [PASS] AgentContract doctor executed zero elevated sandbox, ACL, or process termination commands")
    print("  [PASS] Disposable smoke session resources cleaned up completely")
    print("  [NOT OBSERVED] External system ACLs, unmanaged background processes, untracked subdirectory contents, and Desktop GUI state not monitored")

    print("\nSummary:")
    print("  AgentContract Codex hooks are healthy, validated, and isolated.")

    print("\nUpstream Environment Advisory:")
    print("  Live Codex CLI execution requires upstream Codex runtime compatibility.")
    print("  If upstream Codex encounters Windows sandbox policy restrictions")
    print("  (such as 'CreateProcess ... rejected: blocked by policy' or 'os error 32'),")
    print("  these are external upstream environment issues. AgentContract will not")
    print("  force unsafe elevated sandbox setup, modify system ACLs, or bypass sandbox.")
    print("=" * 60)
    return 0

