# TASK-012 — Codex CLI PreToolUse Output Protocol Compatibility

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M7 — Codex Runtime Protocol Compatibility  
**Owner:** Execution agent  
**Work branch:** `task/TASK-012-codex-pretooluse-compat`  
**Main-agent review:** Pending execution

## Objective

Fix compatibility between AgentContract PreToolUse hook output and Codex CLI (v0.162.0+).

When AgentContract SpecGuard allows a tool call, returning `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}` without `updatedInput` causes Codex CLI runtime to reject the hook output and mark the hook as `Failed`.
Codex CLI protocol expects an empty response (exit code 0 with empty stdout / empty dictionary) when allowing tool execution without modifying arguments.

Conversely, when SpecGuard denies a tool call, the structured denial JSON (`permissionDecision="deny"` with `permissionDecisionReason`) must be preserved and must cleanly prevent tool execution.

## Requirements

1. **ALLOW branch protocol alignment**:
   - In `PreToolUse`, when SpecGuard determines an action is compliant (ALLOW) and no tool input rewriting is performed, return an empty response (`{}` / empty stdout) with exit code 0.
   - Update `PreToolUseOutput` to return an empty dictionary when `permissionDecision == HookDecision.ALLOW` and `updatedInput` is absent.

2. **DENY branch retention**:
   - When SpecGuard blocks an action or when fail-closed safety triggers (session lock timeout, I/O error, state corruption, opaque destructive bash under hard filesystem constraints), maintain the existing structured DENY JSON:
     ```json
     {
       "hookSpecificOutput": {
         "hookEventName": "PreToolUse",
         "permissionDecision": "deny",
         "permissionDecisionReason": "..."
       }
     }
     ```
   - Must not weaken or bypass any constraint checks or fail-closed protections.

3. **Real Codex CLI integration & regression tests**:
   - Update existing unit and integration tests to verify the empty response on ALLOW and structured rejection on DENY.
   - Add real Codex CLI tests in a temporary, isolated workspace with isolated `CODEX_HOME`:
     - **ALLOW execution**: Verify Codex CLI runs a harmless tool (e.g. read file) and records successful/completed tool execution without PreToolUse hook failure.
     - **DENY interception**: Verify Codex CLI attempts a forbidden tool call (e.g. modifying a protected file under a HARD constraint), the hook blocks execution, Codex CLI records the block/denial, and the protected file remains byte-for-byte unchanged.
   - Ensure all tests run with isolated `CODEX_HOME` and never touch user-global `~/.codex`.

4. **Test suite & handoff**:
   - Full pytest suite on Python 3.12.9 must pass.
   - Complete the **Executor Report** section below.
   - Commit and push on branch `task/TASK-012-codex-pretooluse-compat`. Do NOT merge `main`.

## Acceptance Criteria

- `handle_pre_tool_use` returns exit code 0 and empty response `{}` on ALLOW without rewritten input.
- `handle_pre_tool_use` emits structured JSON denial on DENY.
- Automated tests verify real Codex CLI runs on ALLOW and DENY under isolated `CODEX_HOME`.
- Full pytest suite passes with 0 failures on Python 3.12.9.
- Executor Report completed with commit SHA; pushed to remote task branch without merging `main`.

---

## Executor Report

> Execution agent fills this section.

**Implementation summary:**
- Aligned `PreToolUse` output protocol with Codex CLI (v0.162.0+):
  - Updated `PreToolUseOutput` model in `src/agentcontract/integrations/codex/models.py` to support `updatedInput: Mapping[str, Any] | None = None`.
  - Updated `to_hook_response_dict()` so that when `permissionDecision == HookDecision.ALLOW` without `updatedInput`, an empty dictionary `{}` is returned (exits 0 with empty stdout). When `updatedInput` is provided on ALLOW, it is included in the structured dictionary.
  - Kept the structured denial dictionary with `permissionDecision="deny"` and `permissionDecisionReason` intact on DENY branches, ensuring all constraints and fail-closed protections remain fully enforced.
- Updated unit and integration tests across adapter and hooks test suites:
  - `tests/integrations/test_codex_adapter.py`: verified wire contract for ALLOW without rewritten input (`{}`), ALLOW with `updatedInput`, and structured DENY.
  - `tests/integrations/test_codex_hooks.py`: updated ALLOW expectations to assert empty dict `{}` and added `test_pre_tool_use_cli_subprocess_allow_empty_stdout` verifying CLI subprocess returns exit 0 with empty stdout.
  - `tests/integrations/test_codex_cli.py`: added `test_real_codex_cli_pretooluse_allow_completed` verifying harmless tool execution with Codex CLI v0.162.0 succeeds without `PreToolUse Failed` error, and `test_real_codex_cli_pretooluse_deny_blocked` verifying that attempting to write to a protected file under hard constraint is intercepted by PreToolUse, blocked, and the protected file remains byte-for-byte unmodified.
  - Strict isolation: All tests isolate `CODEX_HOME` in temporary directory snapshots, and verify pre/post state of user `~/.codex` ensuring zero modification to real user configurations.

**Files changed:**
- `src/agentcontract/integrations/codex/models.py`
- `tests/integrations/test_codex_adapter.py`
- `tests/integrations/test_codex_hooks.py`
- `tests/integrations/test_codex_cli.py`

**Tests/checks run and results:**
- `python -m pytest tests/integrations/test_codex_adapter.py tests/integrations/test_codex_hooks.py` (37 passed)
- `python -m pytest tests/integrations/test_codex_cli.py` (4 passed, including real Codex CLI executions for ALLOW and DENY)
- `python -m pytest tests/integrations/` (63 passed)
- Full test suite: `python -m pytest` on local Python 3.12.9: **358 passed in 68.28s, 0 failures**.

**Known limitations:**
- None.

**Commit SHA:**
- `98c5eaea7ae56db6e9e88175b90d099cf863ddd0`

**Questions/blockers for main-agent review:**
- None. Everything implemented and verified per TASK-012 specification.

---

## Main Agent Review

> Main agent only.

**Verdict:** PENDING
