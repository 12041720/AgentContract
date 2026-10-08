"""Normalization adapter translating Codex lifecycle hook payloads into AgentContract domain models."""

from collections.abc import Mapping, Sequence
import json
import re
import sys
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
from agentcontract.extraction.claims import ClaimExtractor
from agentcontract.extraction.client import StructuredExtractionClient
from agentcontract.extraction.requirements import RequirementExtractor
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
    Codex patch markers (*** Update File: / *** Add File: / *** Delete File:),
    and Index markers. Discards '/dev/null' and normalizes directory prefixes.
    """
    if not patch_text or not isinstance(patch_text, str):
        return ()

    discovered: list[str] = []

    def _clean_path(raw: str) -> str | None:
        p = raw.strip().strip("'\"")
        p = re.sub(r"[/\\]+", "/", p)
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
        # Skip patch boundary markers
        if any(line_str.startswith(marker) for marker in ("*** Begin", "*** End")):
            continue

        # Codex custom patch headers (*** Update File: path, *** Add File: path, *** Delete File: path)
        if line_str.startswith("*** ") and ":" in line_str:
            raw = line_str.split(":", 1)[1].strip()
            p = _clean_path(raw)
            if p and p not in discovered:
                discovered.append(p)
            continue

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

        # *** path (classic context diff)
        if line_str.startswith("*** ") and not line_str.startswith("*** *"):
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
        cleaned = p.strip().strip("'\"").strip().replace("\\", "/")
        if cleaned and cleaned not in discovered and not cleaned.startswith("-"):
            discovered.append(cleaned)

    # 1. Shell output redirections (> file, >> file)
    for match in re.finditer(r"(?:>|>>)\s*([^\s;&|]+)", command):
        _add(match.group(1))

    # 2. PowerShell parameter paths (-LiteralPath 'file', -Path 'file', -FilePath 'file')
    for match in re.finditer(r"(?:-LiteralPath|-Path|-FilePath)\s+['\"]?([^\s'\";&|]+)", command, re.IGNORECASE):
        _add(match.group(1))

    # 3. Quoted path-like tokens containing an extension
    for match in re.finditer(r"['\"]([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)['\"]", command):
        _add(match.group(1))

    # 4. Common destructive/modifying commands tokens
    cmd_tokens = command.split()
    for token in cmd_tokens:
        if "/" in token or "\\" in token or token.endswith((".key", ".py", ".json", ".txt", ".md", ".env")):
            _add(token)

    return tuple(discovered)


def is_opaque_destructive_command(command: str) -> tuple[bool, str]:
    """Deterministically determine if a shell command is opaque or destructive.

    Returns:
        Tuple of `(is_opaque: bool, reason: str)`.
        If True, the command cannot be statically proven harmless to protected filesystem targets.
    """
    if not command or not isinstance(command, str):
        return False, "empty_command"

    raw = command.strip()
    if not raw:
        return False, "empty_command"

    # Split chained commands (;, &&, ||) and evaluate each sub-command
    sub_commands = re.split(r"(?:\s*;\s*|\s*&&\s*|\s*\|\|\s*)", raw)
    if len(sub_commands) > 1:
        for sub in sub_commands:
            sub = sub.strip()
            if not sub:
                continue
            is_op, reason = is_opaque_destructive_command(sub)
            if is_op:
                return True, f"Chained sub-command '{sub}' is opaque/destructive: {reason}"
        return False, "all_subcommands_safe"

    # 1. Pipeline into shell interpreters (e.g. curl ... | sh, echo ... | bash)
    if re.search(r"\|\s*(?:bash|sh|zsh|pwsh|powershell|cmd|python|python3|py|node|perl|ruby)\b", raw, re.IGNORECASE):
        return True, "Pipeline execution into interpreter or shell"

    # 2. Dynamic evaluation primitives
    if re.search(r"\b(?:eval|exec|source)\s+", raw, re.IGNORECASE) or raw.startswith(". "):
        return True, "Dynamic command evaluation (eval/exec/source)"

    # 3. Wildcard destructive commands (rm *, del *, Remove-Item *, truncate *)
    if re.search(r"\b(?:rm|del|erase|truncate)\b.*[\*\?]", raw, re.IGNORECASE) or re.search(r"\bRemove-Item\b.*[\*\?]", raw, re.IGNORECASE):
        return True, "Wildcard filesystem deletion or truncation"

    # 4. Check for safe test runners without redirection
    has_redirection = bool(re.search(r"(?:>|>>)", raw))
    test_runner_match = re.match(
        r"^(?:pytest|python3?\s+-m\s+pytest|py\s+-m\s+pytest|python3?\s+-m\s+unittest|py\s+-m\s+unittest|npm\s+test|cargo\s+test|go\s+test)\b",
        raw,
        re.IGNORECASE,
    )
    if test_runner_match:
        if has_redirection:
            return True, "Test runner output redirection to file may modify filesystem"
        return False, "safe_test_runner"

    # 5. Check for safe read-only inspection commands without redirection
    safe_read_tools = (
        "cat", "head", "tail", "grep", "rg", "find", "ls", "dir", "tree", "stat",
        "wc", "diff", "file", "pwd", "cd", "type",
        "git status", "git diff", "git log", "git show", "git branch", "git tag", "git rev-parse",
        "get-content", "get-childitem", "get-filehash", "select-string",
    )
    lower_raw = raw.lower()
    for srt in safe_read_tools:
        if lower_raw == srt or lower_raw.startswith(srt + " "):
            if has_redirection:
                return True, f"Inspection command '{srt}' output redirection to file may modify filesystem"
            return False, "safe_read_only"

    # Safe echo / printf without redirection
    if lower_raw.startswith("echo ") or lower_raw.startswith("printf "):
        if not has_redirection and "|" not in raw:
            return False, "safe_echo"

    # 6. Arbitrary interpreter or script execution:
    # python <script.py>, python -c "...", bash <script.sh>, sh ..., pwsh ..., powershell ...
    interpreter_match = re.match(
        r"^(?:python3?|py|node|perl|ruby|bash|sh|zsh|pwsh|powershell|cmd(?:\.exe)?)\b",
        raw,
        re.IGNORECASE,
    )
    if interpreter_match:
        return True, f"Arbitrary interpreter execution ({interpreter_match.group(0)}) cannot statically guarantee filesystem safety"

    # 7. Redirection with variables or wildcards
    if re.search(r"(?:>|>>)\s*[\$\*]", raw):
        return True, "Dynamic or wildcard file redirection"

    # 8. By default, if command contains wildcards:
    if "*" in raw or "?" in raw:
        return True, "Unrecognized command with wildcards cannot statically guarantee filesystem safety"

    return False, "known_command"


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
                or tool_input.get("command")
                or tool_input.get("input")
                or ""
            )
            if not patch_content:
                for v in tool_input.values():
                    if isinstance(v, str) and any(m in v for m in ("*** Begin Patch", "diff --git", "--- ", "+++ ", "*** Update File")):
                        patch_content = v
                        break

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
                action_kind = ActionKind.FILE_DELETE

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
            is_opaque, opaque_reason = is_opaque_destructive_command(command_str)

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
                    "is_opaque": is_opaque,
                    "opaque_reason": opaque_reason,
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
                extractor = RequirementExtractor(client=client)
                extraction = extractor.extract(
                    text=prompt,
                    source=ConstraintSource.USER,
                    author="User",
                    strict=False,
                )
                if extraction.items:
                    return list(extraction.items)
                if extraction.diagnostics:
                    sys.stderr.write(
                        f"[AgentContract] Provider requirement extraction returned {len(extraction.diagnostics)} diagnostic(s) but no constraints.\n"
                    )
            except Exception as exc:
                sys.stderr.write(
                    f"[AgentContract WARNING] Configured provider requirement extraction failed: {exc}. "
                    "Falling back to deterministic rule-based extraction.\n"
                )

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
        session_id: str | None = None,
    ) -> list[Claim]:
        """Extract verifiable completion claims from agent prose."""
        if not prose or not prose.strip():
            return []

        if client is not None:
            try:
                extractor = ClaimExtractor(client=client)
                extraction = extractor.extract(
                    text=prose,
                    trace_id=trace_id,
                    session_id=session_id,
                    strict=False,
                )
                if extraction.items:
                    return list(extraction.items)
                if extraction.diagnostics:
                    sys.stderr.write(
                        f"[AgentContract] Provider claim extraction returned {len(extraction.diagnostics)} diagnostic(s) but no claims.\n"
                    )
            except Exception as exc:
                sys.stderr.write(
                    f"[AgentContract WARNING] Configured provider claim extraction failed: {exc}. "
                    "Falling back to deterministic rule-based extraction.\n"
                )

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
