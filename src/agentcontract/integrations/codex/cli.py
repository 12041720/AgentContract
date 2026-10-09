"""CLI management commands for Codex lifecycle hooks."""

import copy
import json
import os
from pathlib import Path
import sys
import tomllib
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
