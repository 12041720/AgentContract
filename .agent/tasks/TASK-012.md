# TASK-012 — Codex CLI PreToolUse Output Protocol Compatibility

**Status:** CHANGES_REQUESTED  
**Milestone:** M7 — Codex Runtime Protocol Compatibility  
**Owner:** Execution agent  
**Work branch:** `task/TASK-012-codex-pretooluse-compat`  
**Main-agent review:** CHANGES_REQUESTED — round 4

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
- Addressed all Round 4 Main Agent review blockers (Round 5 changes):
  1. **Fixed `action_targets_protected_write()` & Precision Destination Parsing (Blocker 1)**:
     - Replaced substring command check with destination parsing via `extract_write_destinations_from_command()`, accurately extracting write destinations from redirections (`>`, `>>`) and cmdlets/utilities (`Set-Content`, `Out-File`, `Add-Content`, `Remove-Item`, `rm`, `del`, `cp`, `mv`, `tee`, `truncate`).
     - Added `_path_matches()` and `_normalize_path()` to enforce exact path and boundary equality (handles Windows backslashes, leading `./`, absolute path boundaries, and case normalization).
     - Fully prevents false positives:
       - Protected path in `-Value` (e.g. `Set-Content -Path harmless.txt -Value secrets/prod.key`) is correctly identified as a value, not a write target (`False`).
       - Suffix/extension mismatches (e.g. `secrets/prod.key.bak`) are rejected (`False`).
       - Read commands piped to writes on other files (e.g. `Get-Content secrets/prod.key | Out-File harmless.txt`, `cat secrets/prod.key > harmless.txt`) are rejected (`False`).
       - Pure reads (`cat`, `Get-Content`, `type`, `head`) are rejected (`False`).
       - Unsupported/dynamic commands without recognized write targets do not claim precise target correlation (`False`).
     - Expanded `test_action_targets_protected_write_precision` with comprehensive negative and positive fixtures.
  2. **Separated Codex CLI JSONL & AgentContract Trace; Bound by Call ID (Blocker 2)**:
     - Separated Codex CLI JSONL machine event parsing (`parse_codex_cli_items` on `res.stdout`) from AgentContract session trace parsing (`trace.json`).
     - ALLOW correlation: parses completed Codex CLI items and Guard ALLOW events from `trace.json`; requires verifiable correlation by tool call ID or stable probe command mapping; if uncorrelatable, marks `INCONCLUSIVE`.
     - DENY correlation: parses Guard BLOCK decisions from `trace.json` targeting `secrets/prod.key` and collects non-empty `blocked_call_ids` and `blocked_commands`; verifies no successful mutating `TOOL_RESULT` in `trace.json`; verifies no matching completed/successful command item in Codex CLI JSONL; correlates runtime rejection evidence via Codex CLI JSONL failure/block or stderr structured hook denial tied to `blocked_call_ids`, commands, or protected path; marks `INCONCLUSIVE` if uncorrelatable; verifies byte-for-byte SHA-256 hash integrity of `secrets/prod.key`.
     - Updated `src/agentcontract/integrations/codex/hooks.py` to emit `[call_id=...]` tag in stderr SpecGuard BLOCKED messages when `payload.tool_use_id` is present.
     - Added deterministic offline tests `test_codex_cli_event_correlation_allow_logic` and `test_codex_cli_event_correlation_deny_logic`.

**Files changed:**
- `src/agentcontract/integrations/codex/models.py`
- `src/agentcontract/integrations/codex/state.py`
- `src/agentcontract/integrations/codex/hooks.py`
- `tests/integrations/test_codex_adapter.py`
- `tests/integrations/test_codex_hooks.py`
- `tests/integrations/test_codex_cli.py`
- `.agent/tasks/TASK-012.md`

**Tests/checks run and results:**
- `python -m pytest tests/integrations/test_codex_cli.py` (7 passed, 2 skipped)
- `python -m pytest tests/integrations/test_codex_hooks.py` (22 passed)
- `python -m pytest tests/integrations/test_codex_adapter.py` (16 passed)
- Full test suite on Python 3.12.9: **362 passed, 2 skipped in 11.74s, 0 failures**.
- Real Codex CLI online E2E tests: both `test_real_codex_cli_pretooluse_allow_completed` and `test_real_codex_cli_pretooluse_deny_blocked` were safely skipped due to absence of dedicated isolated test credentials (`AGENTCONTRACT_TEST_CODEX_AUTH_JSON` / `CODEX_TEST_AUTH_JSON`).
- Zero repository root pollution: `Path(".agentcontract").exists() == False`.
- User original `~/.codex` completely untouched.

**Known limitations:**
- Real online Codex CLI tests (`test_real_codex_cli_pretooluse_allow_completed` and `test_real_codex_cli_pretooluse_deny_blocked`) were explicitly skipped because no separate isolated test credentials (`AGENTCONTRACT_TEST_CODEX_AUTH_JSON` or `CODEX_TEST_AUTH_JSON`) were provided in the local test environment. Live E2E Codex backend integration remains UNVERIFIED until dedicated test credentials are provisioned. User personal auth is strictly uncopied per protocol. Offline pass count (362 passed / 2 skipped) is not claimed as live integration proof.

**Commit SHA:**
- `0876d8c02f8d3c70adbdf71de284d65806e0d55b`

**Questions/blockers for main-agent review:**
- None. Both Round 4 review blockers resolved with destination parsing and call ID correlation; deterministic regression tests added; live online integration explicitly marked UNVERIFIED in the absence of dedicated credentials.

---

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — round 2 (2026-10-09)
**Implementation reviewed:** `0599b50a0c5947a49acbac70400c7775f8f0b0eb`
**Reviewed branch head:** `5ba98f73b12a78fe9795445a9667633e9c0c9609`

### Progress accepted

- Production ALLOW/no updatedInput yields `{}` and empty stdout; structured DENY remains intact.
- Real user auth.json is no longer automatically copied. Online tests require deliberately provisioned `AGENTCONTRACT_TEST_CODEX_AUTH_JSON` or `CODEX_TEST_AUTH_JSON`, otherwise skip.
- CLI test subprocesses set project-local `AGENTCONTRACT_SESSION_DIR` and `cwd`; offline subprocess trace tests demonstrate ALLOW/BLOCK events.
- Executor reports **357 passed, 2 skipped**, with **both real online Codex CLI E2E tests skipped** due to absent test credentials. These results are not independently rerun by main agent.

### BLOCKER 1 — sandbox not explicitly selected in online Codex subprocesses

`tests/integrations/test_codex_cli.py` ALLOW and DENY tests replaced the unrestricted `--dangerously-bypass-approvals-and-sandbox` with `--approve-for-me`, but **do not include `--sandbox workspace-write`**. These are separate controls. The explicit Round 1 acceptance requirement was that the agent be constrained to a temporary workspace by an explicit sandbox mode; do not infer this from `--approve-for-me` or machine defaults. Use `--sandbox workspace-write` (and if needed a safe non-interactive approval setting) in **both** tests, verify effective runtime sandbox in trustworthy CLI metadata, and fail/skip safely if unsupported. Never fall back to unrestricted mode. Keep `--dangerously-bypass-hook-trust` scoped to the synthetic test home/project; no global plugin changes.

### BLOCKER 2 — DENY trace not bound to forbidden attempted tool

Real DENY test currently accepts **any** `GUARD_DECISION=BLOCK` found in any session trace, even if it blocks an unrelated command/unknown tool while the model merely declines to write `secrets/prod.key`. It also keeps permissive prose fallback (`'constraint' in combined_output`). This can falsely claim that the protected write was actually intercepted.

Require evidence from the **specific forbidden action**: parse GUARD_DECISION trace payload (including `action`, `operation`, `paths`, `context.call_id`, or equivalent), confirm it corresponds to attempted `Set-Content ... secrets/prod.key` or another explicit write to that exact protected path, confirm the decision is BLOCK and the structured deny was recognized by the runtime (e.g., trusted hook status/blocked tool evidence). Correlate with tool IDs if available and ensure there is no successful mutating ToolResult for the blocked call. Keep byte-for-byte protected-file hash check. If the agent refuses or never attempts the write, **skip as inconclusive or fail**, do not report passed.

### Verification honesty and online acceptance

The two real online tests are intentionally skipped without separate test credentials; this is safer and acceptable for ordinary offline pytest. However, `Known limitations: None` is inaccurate and the E2E acceptance criterion is **unverified**, not passed. Amend Executor Report to say precisely: 357 passed/2 skipped, real online ALLOW/Completed and DENY/Blocked unverified until opt-in test credentials are provided. Do not claim live integration proof from offline unit tests. No expectation to duplicate users' auth or expose credentials.

### Completion

Keep patch tightly scoped to test safety, evidence correlation, and report accuracy; no need to rewrite production ALLOW/DENY protocol. Run Windows Python 3.12.9 full pytest and report exact pass/skip counts, plus a separate optional real online run result if deliberately provisioned. Commit/push to `task/TASK-012-codex-pretooluse-compat`; **do not merge main**.

**Disposition:** CHANGES_REQUESTED.


### Round 3 review — 2026-10-09

**Verdict:** CHANGES_REQUESTED  
**Implementation reviewed:** `1c4877a90bc60c82f490d5a44a86cf85b903f4e6`  
**Executor report / reviewed branch HEAD:** `9bb6a3325db60ccab7e2b4ebde3a9080092f8722`  
**Review type:** GitHub source/diff and Executor Report static review. No independent Windows Codex run; GitHub reported no combined-status checks.

**Progress:** Both online test commands now explicitly request `--sandbox workspace-write`; the DENY test attempts to inspect the Guard action payload for the protected path; report accurately discloses 357 passed / 2 skipped and live E2E UNVERIFIED. Production ALLOW/no updatedInput and structured DENY paths are unchanged in this round.

**Blocking findings:**

1. **Authenticated DENY test will error before evidence validation.** `tests/integrations/test_codex_cli.py` defines `_action_targets_protected_key(action_data: dict[str, Any])` inside the DENY test, but does not import `Any` and does not enable postponed annotation evaluation. This raises `NameError` if execution reaches the helper definition. Fix the missing import/type and exercise the helper through deterministic tests.

2. **Sandbox evidence assertion is ineffective.** The ALLOW test runs `assert ev["sandbox"] == "workspace-write"` inside `try: ... except Exception: pass`; `AssertionError` is swallowed. The event's sandbox field is also optional, so absence passes. Parse JSON with narrow `JSONDecodeError` handling; enforce trustworthy runtime sandbox evidence when available, and label missing/unrecognized metadata explicitly UNVERIFIED rather than claiming it was verified. Keep the explicit bounded CLI flag and never use an unrestricted fallback.

3. **DENY success can still be falsely inferred.** `_action_targets_protected_key` searches for the protected path as a substring in arbitrary operation/command text without proving that action is a write/delete; a read/reference or unrelated fail-closed BLOCK can qualify. `found_targeted_block` can be true with **zero** correlated `blocked_call_ids`, making the successful-result exclusion vacuous. Strings such as `"BLOCK:"` in combined output can originate in agent prose, not trusted hook status. Require a verified mutating operation against normalized exact protected path, a nonempty matching call ID, Guard decision correlation, a structured runtime hook-denial signal (or other trustworthy machine event), and the unchanged SHA-256; reject inconclusive attempts.

4. **Credential cleanup does not cover setup failure.** The temp `auth.json` copy and hook installation occur before the `try/finally`; exceptions during setup can leave a credential copy behind. In `finally`, unlink failures are swallowed. Move sensitive setup inside guaranteed cleanup scope and make failed cleanup visible; do not use or modify user-global Codex authentication/configuration.

**Acceptance still unverified:** The reported local suite is **357 passed, 2 skipped, 0 failures** on Python 3.12.9; both real online Codex ALLOW/DENY tests intentionally skipped due to absent dedicated test credentials. Offline success is not evidence of Codex CLI runtime recognition. After repairing the tests, run isolated opt-in live evidence using separately provisioned test authentication, or explicitly keep M7 unverified and request an acceptance-scope decision. Never copy the user's global `~/.codex/auth.json`.

**Disposition:** Continue TASK-012 on the same branch. Do not merge `main` or activate TASK-013.


### Round 4 review — 2026-10-09

**Verdict:** CHANGES_REQUESTED  
**Implementation reviewed:** `0ce55af4b423e09f43f32eccde25d2c890413772`  
**Reviewed branch head:** `0493fb543f18c0709388cf1ef8fc8ed70e294140`  
**Evidence scope:** GitHub source/diff and Executor Report static review; no independent Codex CLI/Windows execution; GitHub combined status has no checks.

**Confirmed progress:** The missing `Any` import is fixed, JSON parsing no longer catches `AssertionError`, a non-empty blocked call ID is now required, and temporary test auth setup is inside `try/finally` with explicit unlink. Explicit `--sandbox workspace-write` remains. Executor reports Python 3.12.9 **360 passed / 2 skipped / 0 failures**, including three new offline tests; both actual Codex CLI online ALLOW/DENY tests skipped for absent opt-in credentials. These are executor-reported results, not independently rerun.

**BLOCKER 1 — false-positive mutating target identification:** `action_targets_protected_write()` still checks `norm_target in cmd_normalized` then a write indicator anywhere in the command. `Set-Content -Path harmless.txt -Value secrets/prod.key` would be classified as a protected write although the protected path is a value, not the write destination; `Set-Content -Path secrets/prod.key.bak -Value X` also matches the protected path as substring. A read of the protected path piped into a write to another file can be misclassified. Parse the destination(s) of each mutating command/redirect and compare normalized exact paths (including Windows forms and boundaries). For unsupported/dynamic commands do not claim precise target correlation. Add negative fixtures for these cases alongside positive cases.

**BLOCKER 2 — runtime denial evidence is not matched to the blocked call:** `all_events` comes from AgentContract `trace.json` and contains `event_kind`/payload trace events; checking those for a Codex CLI `item.type == command_execution` machine event does not validate an actual Codex status. The remaining stderr string alternatives do not tie a Codex runtime rejection to `blocked_call_ids`; they may refer to a separate hook/call. Parse Codex CLI JSONL from `res.stdout` separately, correlate the attempted call and matching Guard BLOCK/structured hook denial using IDs or a demonstrably equivalent stable mapping. If the runtime does not expose enough to establish that relation, mark the result INCONCLUSIVE rather than passing. Assert no matching successful ToolResult and protected-file bytes remain unchanged. Also make the ALLOW completed action correspond to its Guard ALLOW, not just any trace ALLOW.

**Evidence gate still open:** Ordinary offline pytest may skip the two online E2E tests without accessing real user auth, but M7's explicit real Codex acceptance criterion remains UNVERIFIED. Do not count `360 passed / 2 skipped` as online success or merge. Run the corrected two E2E tests only with dedicated opt-in test authentication and isolated CODEX_HOME, bounded workspace-write sandbox and trusted runtime evidence. If credentials are unavailable, report BLOCKED/UNVERIFIED for E2E and do not repeat a generic success claim. Sandbox metadata is checked only when emitted; absence is not positive proof of effective sandbox.

**Disposition:** Continue TASK-012 in same task branch; fix both blockers and obtain real E2E proof, or surface a precise credential blocker for an acceptance-scope decision. Do not merge product code to `main` or activate TASK-013.
