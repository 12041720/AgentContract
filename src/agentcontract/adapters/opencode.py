"""OpenCode project-level plugin adapter and SpecGuard bridge."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStatus,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.guard.engine import SpecGuard
from agentcontract.guard.models import Action, ActionKind, DecisionKind, GuardDecision
from agentcontract.trace.models import TracePointer


def normalize_rel_path(path_str: str, project_dir: Path | None = None) -> str:
    """Normalize a path to a consistent forward-slash relative path when possible."""
    norm = path_str.strip().replace("\\", "/")
    if project_dir is not None:
        try:
            resolved_p = Path(path_str)
            if resolved_p.is_absolute():
                norm = resolved_p.relative_to(project_dir.resolve()).as_posix()
        except (ValueError, Exception):
            pass
    # Strip leading ./
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def parse_opencode_tool_to_action(
    tool: str,
    args: Mapping[str, Any],
    call_id: str,
    session_id: str,
    project_dir: Path | None = None,
) -> Action:
    """Convert an OpenCode tool invocation into an AgentContract Action."""
    tool_lower = (tool or "").strip().lower()
    t_paths: list[str] = []

    # Extract target paths from arguments
    for key in ("filePath", "file_path", "path", "file", "target", "destination"):
        if key in args and isinstance(args[key], str) and args[key].strip():
            raw_p = args[key].strip()
            norm_p = normalize_rel_path(raw_p, project_dir)
            if norm_p not in t_paths:
                t_paths.append(norm_p)
            # Also keep raw basename or original relative path if useful
            base_p = Path(raw_p).name
            if base_p and base_p not in t_paths:
                t_paths.append(base_p)

    target_path = t_paths[0] if t_paths else None
    action_kind = ActionKind.TOOL_CALL
    operation = tool_lower
    target_type = "tool"

    if tool_lower in ("write", "create_file", "save_file"):
        action_kind = ActionKind.FILE_WRITE
        target_type = "filesystem"
        operation = "write"
    elif tool_lower in ("edit", "apply_patch", "patch", "modify_file"):
        action_kind = ActionKind.FILE_WRITE
        target_type = "filesystem"
        operation = "edit"
    elif tool_lower in ("read", "view_file", "get_file", "read_file"):
        action_kind = ActionKind.FILE_READ
        target_type = "filesystem"
        operation = "read"
    elif tool_lower in ("delete", "remove_file", "unlink"):
        action_kind = ActionKind.FILE_DELETE
        target_type = "filesystem"
        operation = "delete"
    elif tool_lower in ("bash", "powershell", "pwsh", "cmd", "command", "terminal", "exec"):
        action_kind = ActionKind.COMMAND_EXEC
        target_type = "filesystem"
        cmd_str = str(args.get("command") or args.get("cmd") or "")
        operation = cmd_str
        # Extract potential paths referenced in command
        for token in re.findall(r"[\w./\\-]+(?:\.[\w]+)?", cmd_str):
            if "/" in token or "\\" in token or "." in token:
                norm_tok = normalize_rel_path(token, project_dir)
                if norm_tok not in t_paths:
                    t_paths.append(norm_tok)

    return Action(
        action_kind=action_kind,
        tool_name=tool,
        target_type=target_type,
        target_path=target_path,
        paths=tuple(t_paths),
        operation=operation,
        payload=FrozenDict(args),
        context=FrozenDict({"session_id": session_id, "call_id": call_id}),
        trace_pointer=None,
    )


def load_manifest_constraints(manifest_path: Path) -> list[Constraint]:
    """Load deterministic versioned constraints from a project manifest file."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"AgentContract manifest not found at {manifest_path}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_constraints = data.get("constraints", [])
    constraints: list[Constraint] = []

    for raw in raw_constraints:
        c_id = str(raw["id"])
        c_name = str(raw.get("name", c_id))
        c_desc = str(raw.get("description", ""))
        strength = ConstraintStrength(raw.get("strength", "HARD").upper())
        effect = RuleEffect(raw.get("effect", "DENY").upper())

        raw_scope = raw.get("scope", {})
        scope = ConstraintScope(
            target_type=raw_scope.get("target_type"),
            paths=tuple(raw_scope.get("paths", ())),
            tools=tuple(raw_scope.get("tools", ())),
            actions=tuple(raw_scope.get("actions", ())),
            description=raw_scope.get("description"),
        )

        c = Constraint(
            id=c_id,
            name=c_name,
            description=c_desc,
            source=ConstraintSource.POLICY,
            strength=strength,
            status=ConstraintStatus.ACTIVE,
            effect=effect,
            scope=scope,
            provenance=ConstraintProvenance(
                source=ConstraintSource.POLICY,
                source_location=str(manifest_path),
                source_text=c_desc,
            ),
        )
        constraints.append(c)

    return constraints


def evaluate_opencode_tool_call(
    project_dir: Path,
    tool: str,
    args: Mapping[str, Any],
    call_id: str,
    session_id: str,
    manifest_rel_path: str = ".agentcontract/manifest.json",
    trace_rel_path: str = ".agentcontract/guard_trace.jsonl",
) -> dict[str, Any]:
    """Evaluate an OpenCode tool call against project SpecGuard constraints."""
    manifest_file = project_dir / manifest_rel_path
    trace_file = project_dir / trace_rel_path
    trace_file.parent.mkdir(parents=True, exist_ok=True)

    # If project does not have an opt-in manifest, it's not a guarded project
    if not manifest_file.exists():
        return {
            "decision": "ALLOW",
            "reasons": ["No active AgentContract manifest in project."],
            "violating_constraint_ids": [],
        }

    try:
        constraints = load_manifest_constraints(manifest_file)
        ledger = ConstraintLedger()
        for c in constraints:
            ledger.add(c)

        action = parse_opencode_tool_to_action(
            tool=tool,
            args=args,
            call_id=call_id,
            session_id=session_id,
            project_dir=project_dir,
        )

        spec_guard = SpecGuard()
        decision: GuardDecision = spec_guard.evaluate(action, ledger=ledger)

        # Log trace event
        trace_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "GUARD_DECISION",
            "decision": decision.decision.value,
            "call_id": call_id,
            "session_id": session_id,
            "tool": tool,
            "action_kind": action.action_kind.value if action.action_kind else None,
            "target_path": action.target_path,
            "paths": list(action.paths),
            "reasons": list(decision.reasons),
            "violating_constraint_ids": list(decision.violating_constraint_ids),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace_entry) + "\n")

        return {
            "decision": decision.decision.value,
            "reasons": list(decision.reasons),
            "violating_constraint_ids": list(decision.violating_constraint_ids),
        }

    except Exception as e:
        # Fail-closed for file mutation / command execution if an error occurs under active guard
        err_msg = f"AgentContract evaluation error: {e}"
        err_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "GUARD_ERROR",
            "call_id": call_id,
            "session_id": session_id,
            "error": str(e),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(err_entry) + "\n")

        return {
            "decision": "BLOCK",
            "reasons": [err_msg],
            "violating_constraint_ids": ["ERR_FAIL_CLOSED"],
        }


def build_opencode_plugin_js(
    python_exe: str | None = None,
    bridge_module: str = "agentcontract.adapters.opencode_bridge",
) -> str:
    """Generate the JavaScript/TypeScript plugin source code for OpenCode."""
    py_cmd = python_exe or sys.executable
    # Escape backslashes for JS string literal
    py_cmd_escaped = py_cmd.replace("\\", "\\\\")

    return f"""import {{ spawnSync }} from 'child_process'
import * as fs from 'fs'
import * as path from 'path'

export const AgentContractPlugin = async ({{ directory }}) => {{
  const manifestPath = path.join(directory, '.agentcontract', 'manifest.json')
  const traceLog = path.join(directory, '.agentcontract', 'guard_trace.jsonl')

  // Boundary check: if no AgentContract manifest exists, remain inert
  if (!fs.existsSync(manifestPath)) {{
    return {{}}
  }}

  // Ensure log directory exists
  const logDir = path.dirname(traceLog)
  if (!fs.existsSync(logDir)) {{
    fs.mkdirSync(logDir, {{ recursive: true }})
  }}

  const pythonBin = "{py_cmd_escaped}"

  return {{
    'tool.execute.before': async (input, output) => {{
      const tool = input?.tool || 'unknown'
      const args = output?.args || {{}}
      const callID = input?.callID || 'call_' + Date.now()
      const sessionID = input?.sessionID || 'unknown'

      const reqPayload = JSON.stringify({{
        project_dir: directory,
        tool: tool,
        call_id: callID,
        session_id: sessionID,
        args: args
      }})

      try {{
        const res = spawnSync(pythonBin, ['-m', '{bridge_module}', 'check'], {{
          input: reqPayload,
          encoding: 'utf-8',
          timeout: 10000,
          windowsHide: true
        }})

        if (res.error) {{
          throw new Error('Bridge execution failed: ' + res.error.message)
        }}

        const stdout = (res.stdout || '').trim()
        let result = {{ decision: 'ALLOW' }}
        if (stdout) {{
          try {{
            result = JSON.parse(stdout)
          }} catch (e) {{
            throw new Error('Failed to parse bridge JSON: ' + stdout)
          }}
        }}

        if (result.decision === 'BLOCK') {{
          const blockReason = (result.reasons && result.reasons[0]) || 'Policy violation'
          const blockMsg = 'AgentContract BLOCK: ' + blockReason
          throw new Error(blockMsg)
        }}
      }} catch (err) {{
        // Re-throw if already an AgentContract BLOCK exception
        if (err.message && err.message.startsWith('AgentContract BLOCK:')) {{
          throw err
        }}
        // Fail closed on bridge error
        throw new Error('AgentContract BLOCK (Bridge Error): ' + err.message)
      }}
    }},

    'tool.execute.after': async (input, output) => {{
      const tool = input?.tool || 'unknown'
      const callID = input?.callID || 'unknown'
      const sessionID = input?.sessionID || 'unknown'

      const afterEntry = {{
        timestamp: new Date().toISOString(),
        event: 'TOOL_RESULT_OBSERVED',
        call_id: callID,
        session_id: sessionID,
        tool: tool,
        title: output?.title,
        output_snippet: typeof output?.output === 'string' ? output.output.slice(0, 300) : undefined
      }}
      try {{
        fs.appendFileSync(traceLog, JSON.stringify(afterEntry) + '\\n')
      }} catch (_) {{}}
    }}
  }}
}}

export default AgentContractPlugin
"""
