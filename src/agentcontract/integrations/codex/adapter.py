"""Normalization adapter translating Codex lifecycle hook payloads into AgentContract domain models."""

from collections.abc import Mapping, Sequence
import json
import re
from typing import Any

from agentcontract.adapters.tool_events import ToolEventAdapter
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.evidence.models import Claim, ClaimType
from agentcontract.extraction.client import StructuredExtractionClient
from agentcontract.guard.models import Action, ActionKind
from agentcontract.integrations.codex.models import (
    PostToolUsePayload,
    PreToolUsePayload,
)
from agentcontract.trace.models import (
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


def parse_patch_paths(patch_text: str) -> tuple[str, ...]:
    """Deterministically extract all affected target paths from a unified diff / patch.

    Extracts paths from git diff headers, unified diff (--- / +++), context diff (***),
    and Index markers. Discards '/dev/null' and normalizes directory prefixes.
    """
    if not patch_text or not isinstance(patch_text, str):
        return ()

    discovered: list[str] = []

    def _clean_path(raw: str) -> str | None:
        p = raw.strip().strip("'\"")
        # Remove trailing timestamp if present (e.g. +++ file.txt 2026-09-30 ...)
        p = re.split(r"\s+", p)[0]
        if not p or p == "/dev/null":
            return None
        # Strip common git prefixes a/ or b/
        if p.startswith("a/") or p.startswith("b/"):
            p = p[2:]
        p = p.strip().strip("/")
        return p or None

    lines = patch_text.splitlines()
    for line in lines:
        line_str = line.strip()
        # diff --git a/path b/path
        if line_str.startswith("diff --git "):
            parts = line_str.split()
            if len(parts) >= 4:
                p1 = _clean_path(parts[2])
                p2 = _clean_path(parts[3])
                if p1 and p1 not in discovered:
                    discovered.append(p1)
                if p2 and p2 not in discovered:
                    discovered.append(p2)
            continue

        # +++ b/path or +++ path
        if line_str.startswith("+++ "):
            raw = line_str[4:].strip()
            p = _clean_path(raw)
            if p and p not in discovered:
                discovered.append(p)
            continue

        # --- a/path or --- path
        if line_str.startswith("--- "):
            raw = line_str[4:].strip()
            p = _clean_path(raw)
            if p and p not in discovered:
                discovered.append(p)
            continue

        # *** path
        if line_str.startswith("*** "):
            raw = line_str[4:].strip()
            p = _clean_path(raw)
            if p and p not in discovered:
                discovered.append(p)
            continue

        # Index: path
        if line_str.startswith("Index: "):
            raw = line_str[7:].strip()
            p = _clean_path(raw)
            if p and p not in discovered:
                discovered.append(p)
            continue

    return tuple(discovered)


def parse_command_paths(command: str) -> tuple[str, ...]:
    """Extract obvious filesystem paths targeted or affected by a shell command."""
    if not command or not isinstance(command, str):
        return ()

    discovered: list[str] = []

    def _add(p: str) -> None:
        cleaned = p.strip().strip("'\"").strip()
        if cleaned and cleaned not in discovered and not cleaned.startswith("-"):
            discovered.append(cleaned)

    # 1. Shell output redirections (> file, >> file)
    for match in re.finditer(r"(?:>|>>)\s*([^\s;&|]+)", command):
        _add(match.group(1))

    # 2. Common destructive/modifying commands: rm, cp, mv, touch, cat, echo, truncate, sed
    cmd_tokens = command.split()
    for token in cmd_tokens:
        # Check for path-like structures containing / or \ or known extensions
        if ("/" in token or "\\" in token or token.endswith((".key", ".py", ".json", ".txt", ".md", ".env"))):
            _add(token)

    return tuple(discovered)


class CodexHookAdapter:
    """Translates Codex lifecycle payloads into AgentContract domain objects."""

    @classmethod
    def to_action(cls, payload: PreToolUsePayload) -> Action:
        """Normalize a Codex PreToolUse hook payload into a SpecGuard Action."""
        tool_name = payload.tool_name.strip()
        tname_lower = tool_name.lower()
        tool_input = dict(payload.tool_input or {})

        call_id = payload.tool_use_id or f"codex_call_{abs(hash(str(payload.tool_input)))}"

        # 1. Handle apply_patch (and aliases patch, edit, write_patch)
        if any(alias in tname_lower for alias in ("apply_patch", "patch", "edit_file", "patch_file")):
            patch_content = (
                tool_input.get("patch")
                or tool_input.get("diff")
                or tool_input.get("content")
                or ""
            )
            extracted_paths = list(parse_patch_paths(str(patch_content)))

            # If explicit path or file_path is given in tool_input, include it
            for pkey in ("path", "file_path", "file", "target_path"):
                val = tool_input.get(pkey)
                if isinstance(val, str) and val.strip() and val.strip() not in extracted_paths:
                    extracted_paths.append(val.strip())

            all_paths = tuple(extracted_paths)
            primary_path = all_paths[0] if all_paths else None

            action_kind = ActionKind.FILE_WRITE
            if "delete" in str(patch_content).lower() or "/dev/null" in str(patch_content):
                action_kind = ActionKind.FILE_WRITE  # Guard checks both or specific actions

            return Action(
                action_kind=action_kind,
                tool_name=tool_name,
                target_path=primary_path,
                paths=all_paths,
                target_type="filesystem",
                operation="apply_patch",
                payload=tool_input,
                context={
                    "call_id": call_id,
                    "patch_paths_count": len(all_paths),
                    "all_paths": all_paths,
                    "session_id": payload.session_id,
                },
            )

        # 2. Handle Bash / shell commands
        if any(alias in tname_lower for alias in ("bash", "sh", "command", "exec", "shell", "run_command")):
            command_str = str(
                tool_input.get("command")
                or tool_input.get("cmd")
                or tool_input.get("input")
                or ""
            )
            cmd_paths = parse_command_paths(command_str)
            primary_path = cmd_paths[0] if cmd_paths else None

            # Policy: if command targets a filesystem path, note target_type as filesystem
            target_type = "filesystem" if cmd_paths else "command"

            return Action(
                action_kind=ActionKind.COMMAND_EXEC,
                tool_name=tool_name,
                target_path=primary_path,
                paths=cmd_paths,
                target_type=target_type,
                operation=command_str,
                payload=tool_input,
                context={
                    "call_id": call_id,
                    "command": command_str,
                    "target_paths": cmd_paths,
                    "session_id": payload.session_id,
                },
            )

        # 3. Handle general tools / MCP tools
        tool_call_dict = {
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": tool_input,
        }
        return ToolEventAdapter.to_action(
            tool_call_dict,
            context={"session_id": payload.session_id},
        )

    @classmethod
    def to_tool_call(cls, payload: PreToolUsePayload | PostToolUsePayload) -> ToolCall:
        """Construct validated ToolCall from hook payload."""
        call_id = payload.tool_use_id or f"codex_call_{abs(hash(str(payload.tool_input)))}"
        return ToolCall(
            call_id=call_id,
            tool_name=payload.tool_name,
            arguments=dict(payload.tool_input or {}),
        )

    @classmethod
    def to_tool_result(cls, payload: PostToolUsePayload) -> ToolResult:
        """Construct validated ToolResult from PostToolUse payload."""
        call_id = payload.tool_use_id or f"codex_call_{abs(hash(str(payload.tool_input)))}"
        resp = payload.tool_response

        # Determine status and exit code
        status = ToolResultStatus.SUCCESS
        exit_code: int | None = None
        error_msg: str | None = None

        if isinstance(resp, Mapping):
            if "exit_code" in resp:
                try:
                    exit_code = int(resp["exit_code"])
                except (ValueError, TypeError):
                    pass
            elif "status_code" in resp:
                try:
                    exit_code = int(resp["status_code"])
                except (ValueError, TypeError):
                    pass

            if resp.get("is_error") or resp.get("error"):
                status = ToolResultStatus.ERROR
                error_msg = str(resp.get("error") or "Tool execution error")
            elif exit_code is not None and exit_code != 0:
                status = ToolResultStatus.ERROR
            elif exit_code is None and status == ToolResultStatus.SUCCESS:
                exit_code = 0
        elif isinstance(resp, str):
            # Check for explicit exit code patterns in text
            exit_m = re.search(r"(?:exit code|status code)[:=]\s*(\d+)", resp, re.IGNORECASE)
            if exit_m:
                exit_code = int(exit_m.group(1))

            if "error:" in resp.lower() or "exception:" in resp.lower() or (exit_code is not None and exit_code != 0):
                status = ToolResultStatus.ERROR
                error_msg = resp
            else:
                status = ToolResultStatus.SUCCESS
                if exit_code is None:
                    exit_code = 0

        return ToolResult(
            call_id=call_id,
            status=status,
            output=resp,
            exit_code=exit_code,
            error=error_msg,
        )

    @classmethod
    def extract_prompt_constraints(
        cls,
        prompt: str,
        client: StructuredExtractionClient | None = None,
    ) -> list[Constraint]:
        """Extract enforceable constraints from user prompt."""
        if not prompt or not prompt.strip():
            return []

        # If extraction client provided, run model extraction
        if client is not None:
            try:
                extraction = client.extract_requirements(prompt)
                return list(extraction.constraints)
            except Exception:
                pass

        # Deterministic rule-based extraction fallback
        constraints: list[Constraint] = []
        text = prompt.strip()

        # Check for explicit protected paths ("do not modify/delete/touch <path>")
        protected_patterns = [
            r"(?:do\s+not|never|prohibit|forbidden|must\s+not)\s+[^.!?\n]*?(?:modify|write|delete|touch|remove|change|overwrite)[^.!?\n]*?['\"]?([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)['\"]?",
            r"['\"]?([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)['\"]?[^.!?\n]*?(?:hard\s+protected\s+file|must\s+not\s+be\s+modified)",
        ]
        for pattern in protected_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                target = match.group(1).strip()
                cid = f"deny_protect_{abs(hash(target)) % 10000000:07d}"
                constraints.append(
                    Constraint(
                        id=cid,
                        name=f"protect_{target.replace('/', '_').replace('.', '_')}",
                        description=f"Do not modify or delete protected file '{target}'.",
                        strength=ConstraintStrength.HARD,
                        rule_effect=RuleEffect.DENY,
                        provenance=ConstraintProvenance(
                            source=ConstraintSource.USER,
                            source_text=prompt[:200],
                            author="User",
                        ),
                        scope=ConstraintScope(
                            target_type="filesystem",
                            paths=(target,),
                            actions=("FILE_WRITE", "FILE_DELETE", "COMMAND_EXEC", "apply_patch"),
                        ),
                    )
                )

        return constraints

    @classmethod
    def extract_completion_claims(
        cls,
        prose: str,
        trace_id: str,
        client: StructuredExtractionClient | None = None,
    ) -> list[Claim]:
        """Extract verifiable completion claims from agent prose."""
        if not prose or not prose.strip():
            return []

        if client is not None:
            try:
                extraction = client.extract_claims(prose, trace_id=trace_id)
                return list(extraction.claims)
            except Exception:
                pass

        # Deterministic extraction fallback
        claims: list[Claim] = []
        text = prose.strip()

        # 1. Tests passed claim
        if re.search(r"\bpytest\b.*(?:pass|succeed|exit\s*code\s*0|0\s*fail)", text, re.IGNORECASE):
            claims.append(
                Claim(
                    claim_id=f"cl_test_{abs(hash(text)) % 1000000:06d}",
                    claim_type=ClaimType.TESTS_PASSED,
                    description="All tests passed successfully with pytest",
                    trace_id=trace_id,
                    command="pytest",
                    expected_exit_code=0,
                )
            )

        # 2. File exists claim
        file_matches = re.finditer(
            r"(?:generated|created|wrote|updated|saved)\s+(?:the\s+)?(?:file\s+)?(?:at\s+)?['\"]?([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)['\"]?",
            text,
            re.IGNORECASE,
        )
        for match in file_matches:
            fpath = match.group(1).strip()
            claims.append(
                Claim(
                    claim_id=f"cl_file_{abs(hash(fpath)) % 1000000:06d}",
                    claim_type=ClaimType.FILE_EXISTS,
                    description=f"Generated file at {fpath}",
                    trace_id=trace_id,
                    target_path=fpath,
                )
            )

        return claims
