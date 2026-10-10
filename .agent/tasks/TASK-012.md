# TASK-012 — Codex CLI PreToolUse Output Protocol Compatibility

**Status:** CHANGES_REQUESTED  
**Milestone:** M7 — Codex Runtime Protocol Compatibility  
**Owner:** Execution agent  
**Work branch:** `task/TASK-012-codex-pretooluse-compat`  
**Main-agent review:** CHANGES_REQUESTED — round 9

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
- Addressed all Round 5 Main Agent review blockers:
  1. **Fixed quoted redirection false positives & workspace-aware path matching (Round 5 Blocker 1)**:
     - Implemented quote-aware redirection extraction `extract_unquoted_redirections()` and quote-aware pipeline splitting `split_unquoted_pipeline()`. Redirections (`>`, `>>`) inside single or double quotes (e.g. `echo 'look > secrets/prod.key'` and `Set-Content -Path harmless.txt -Value 'note > secrets/prod.key'`) are ignored and no longer produce false positive write targets.
     - Updated `_path_matches()` and `action_targets_protected_write()` to resolve absolute paths against `workspace_root` (or context `cwd`/`workspace`). Foreign cross-workspace absolute paths (e.g. `C:/other_workspace/secrets/prod.key`) are rejected (`False`).
     - Added comprehensive regression negative tests in `test_action_targets_protected_write_precision` for quoted redirections and foreign cross-workspace absolute paths.
  2. **Strict ALLOW completion & independent Codex runtime DENY proof (Round 5 Blocker 2)**:
     - ALLOW test (`test_real_codex_cli_pretooluse_allow_completed`): requires terminal completed/successful status (`status in ("completed", "success")`, exit code 0 or None, and probe content verification). Rejects `in_progress`, pending, failed, or blocked. Updated `test_codex_cli_event_correlation_allow_logic` with deterministic negative assertions.
     - DENY test (`test_real_codex_cli_pretooluse_deny_blocked`): hook's own stderr logs (`[AgentContract SpecGuard] BLOCKED ...`) are strictly excluded as proof of Codex honoring the block. Verification requires independent proof from the Codex CLI runtime: a machine event in Codex CLI JSONL with failed/blocked/denied/cancelled status or hook rejection error, OR distinct Codex runtime stderr diagnostics (excluding hook logs) tied to the blocked call/command, along with byte-for-byte SHA-256 hash preservation and absence of successful `ToolResult`. If unproven, marks `INCONCLUSIVE`.
     - Separated Guard trace `call_id` and Codex event IDs until correspondence is established.
  3. **Corrected commit SHA provenance (Round 5 Blocker 3)**:
     - Replaced non-retrievable amended commit SHA with the verified, reachable implementation commit SHA pushed to remote branch `task/TASK-012-codex-pretooluse-compat`.
- Addressed Round 7 Main Agent review:
  4. **Resolved Codex CLI Argument Conflict (Round 7 Review)**:
     - Removed the incompatible `"--approve-for-me"` flag from both `test_real_codex_cli_pretooluse_allow_completed` and `test_real_codex_cli_pretooluse_deny_blocked` subprocess invocations in `tests/integrations/test_codex_cli.py`, eliminating the `cannot be used with '--approve-for-me'` CLI parser exit code 2 error.
     - Retained mandatory `"--sandbox", "workspace-write"`, `"--dangerously-bypass-hook-trust"`, `"--skip-git-repo-check"`, `-C <proj>`, `--json`, isolated `CODEX_HOME`, and project-local `AGENTCONTRACT_SESSION_DIR`. Never using unrestricted `--dangerously-bypass-approvals-and-sandbox`.
     - Added in-test assertions in both scenarios verifying flag configuration before subprocess execution.
     - Added deterministic offline regression test `test_codex_cli_e2e_flag_compatibility` that parses the AST of `cmd` in both scenarios to guarantee `--approve-for-me` is absent and `--sandbox workspace-write` is present.

**Files changed:**
- `src/agentcontract/integrations/codex/models.py`
- `src/agentcontract/integrations/codex/state.py`
- `src/agentcontract/integrations/codex/hooks.py`
- `tests/integrations/test_codex_adapter.py`
- `tests/integrations/test_codex_hooks.py`
- `tests/integrations/test_codex_cli.py`
- `.agent/tasks/TASK-012.md`

**Tests/checks run and results:**
- `python -m pytest tests/integrations/test_codex_cli.py` (8 passed, 2 skipped)
- `python -m pytest tests/integrations/test_codex_hooks.py` (22 passed)
- `python -m pytest tests/integrations/test_codex_adapter.py` (16 passed)
- Full test suite on Python 3.12.9: **363 passed, 2 skipped in 14.01s, 0 failures**.
- Real Codex CLI online E2E tests: both `test_real_codex_cli_pretooluse_allow_completed` and `test_real_codex_cli_pretooluse_deny_blocked` safely skip when dedicated isolated test credentials (`AGENTCONTRACT_TEST_CODEX_AUTH_JSON` / `CODEX_TEST_AUTH_JSON`) are absent from the environment.
- Zero repository root pollution: `Path(".agentcontract").exists() == False`.
- User original `~/.codex` completely untouched.

**Known limitations / E2E Acceptance Status:**
- The CLI flag incompatibility between `--sandbox workspace-write` and `--approve-for-me` is resolved.
- Real online Codex CLI tests will be executed and validated with dedicated test credentials.

**Commit SHA:**
- `62260ac4f7db0fa0ac9bfdffeb6a3826ac6e252d`

**Questions/blockers for main-agent review:**
- None. Flag conflict resolved and verified via AST regression test; stopping as instructed for user-arranged authenticated live E2E rerun.

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


### Round 5 review — 2026-10-10

**Verdict:** CHANGES_REQUESTED  
**Reviewed remote branch HEAD:** `2741178152075a8aaa310ceb02b64e77a598023d`  
**Executor Report implementation SHA:** `0876d8c02f8d3c70adbdf71de284d65806e0d55b` (GitHub returned 422 / no commit found for that SHA).  
**Review scope:** GitHub static source/diff and Executor Report; no independent Windows Codex runtime rerun. GitHub combined status has no checks; attempting to obtain a clone locally failed with GitHub DNS resolution error.

**Progress:** The previous value-vs-destination cases were substantially improved by explicit shell destination extraction; Codex CLI JSONL and AgentContract trace are now handled separately; stderr BLOCK lines include a tool_use_id tag when available. Executor reports **362 passed, 2 skipped, 0 failures** on Python 3.12.9. Both required real online ALLOW/DENY E2E tests are **SKIPPED** for absent dedicated test authentication and therefore **UNVERIFIED**. No real runtime success can be inferred.

**BLOCKER 1 — shell destination extraction still produces a false positive from quoted data.** `extract_write_destinations_from_command()` applies the `>` redirection regex to the entire unlexed string, including quoted strings. For example, `echo 'look > secrets/prod.key'` contains no redirection, but the regex captures `secrets/prod.key'`, and `_normalize_path` strips the trailing quote; the helper classifies it as protected write. Likewise `Set-Content -Path harmless.txt -Value 'note > secrets/prod.key'` should not correlate to writing the protected file. Also `_path_matches()` accepts *any* absolute path ending `/secrets/prod.key`, including a different project, rather than resolving against the temp workspace root. Redirection detection must be quote-aware and destination comparison must be workspace-aware. Add both negative cases to deterministic tests.

**BLOCKER 2 — runtime execution/denial evidence remains insufficient.** ALLOW `completed_codex_items` includes `command_execution` items with any status other than `failed`, including `in_progress`, empty or `blocked`, so it can report a completed action without completion. Require actual terminal successful item evidence. DENY treats the hook's *own* stderr `[AgentContract SpecGuard] BLOCKED [call_id=...]` as proof that Codex accepted/obeyed a denial; it proves the hook evaluated an action, not necessarily that the Codex runtime honored its output. Another stderr fallback matches only `secrets/prod.key`, not a unique call. Demand separate Codex-side blocked/denied result tied to the same call (or independently captured structured hook decision/result and attempted action) plus unchanged file. If Codex does not expose such evidence, explicitly mark INCONCLUSIVE rather than pass. Keep Guard trace `call_id` and Codex event IDs separate until their correspondence is actually established.

**BLOCKER 3 — report provenance:** Executor Report lists implementation commit `0876d8c...`, which could not be retrieved from GitHub (422, no commit found), while the remote branch HEAD is `274117815...`. Correct the report to a verified reachable commit; do not mistake a local or guessed SHA for an accessible pushed commit.

**E2E gate:** M7 requires one trustworthy isolated opt-in Codex CLI ALLOW/Completed and one DENY/Blocked run; ordinary offline pytest is allowed to skip them, but these skips cannot close the task. No personal `~/.codex/auth.json` copy, unrestricted sandbox, global config mutation, or broad machine cleanup. If dedicated test auth is unavailable, stop claiming `fully verified` and treat online acceptance as an explicit blocker requiring a scoped decision, not another test-count increase.

**Disposition:** CHANGES_REQUESTED; TASK-012 remains the sole active task. No product merge to `main` and no TASK-013.


### Round 6 review — 2026-10-10

**Verdict:** BLOCKED — live E2E acceptance prerequisite unavailable; not ACCEPTED  
**Verified implementation commit:** `c7f8bdceb70d6a1eb0a0561a90a10fb080bd89c6` (GitHub fetch succeeded)  
**Reviewed report/branch HEAD:** `4a26d4351063640c44fa435d6f9afa36662b68cf`  
**Review scope:** GitHub static review of source, diff and report; not an independent Windows/Codex CLI run. GitHub reported no combined-status checks.

**Static review progress:** The test helper now scans unquoted redirections, uses workspace-sensitive absolute path matching, and includes negative regression scenarios for quoted redirection and foreign workspace paths. ALLOW test requires terminal completed/success status (and checks exit code when provided). DENY test no longer treats AgentContract's own BLOCKED stderr as sufficient proof; it analyzes Codex JSONL items separately from Guard trace, and asks for a distinct runtime failed/blocked event or diagnostic. Production wire-format fix remains unchanged: empty stdout on ALLOW/no input rewrite, structured JSON on DENY.

**Executor-reported verification:** Local Python 3.12.9 `python -m pytest` **362 passed, 2 skipped, 0 failures**. Both online real Codex CLI E2E tests were deliberately **SKIPPED** because no independently provisioned opt-in test authentication was available in `AGENTCONTRACT_TEST_CODEX_AUTH_JSON` or `CODEX_TEST_AUTH_JSON`. They are **UNVERIFIED**; no live hook acceptance claim is authorized. The main agent has not independently rerun these tests.

**Blocking prerequisite:** Provision a dedicated *test-only* Codex credential within an isolated test environment, without copying user `~/.codex/auth.json` or altering user-global configuration. Then run and preserve authentic, sanitized evidence for both: (a) ALLOW with a completed probe tool action and matching Guard ALLOW, and (b) DENY for an actual protected-file write attempt with matching Guard BLOCK, demonstrably Codex-side hook rejection, no successful mutating tool execution, and unchanged file bytes. `--sandbox workspace-write` and isolated `CODEX_HOME` are mandatory.

**Evidence caution for eventual validation:** A generic Codex JSONL `failed` status could represent a normal command failure rather than a hook rejection. Require proof tying the runtime denial *specifically to PreToolUse* for the blocked call, not merely any failed command or model summary. A missing runtime signal must be treated as inconclusive, not passed. When the first real online run exposes the actual Codex JSONL protocol, adjust the tests only if genuine runtime evidence establishes it.

**Scope decision:** Do not weaken or waive the real online acceptance criterion; do not merge product/test changes to main or activate TASK-013. This task is **BLOCKED**, pending dedicated opt-in test credentials / authentic live evidence. No further offline-only rewrite cycle is requested in the meantime.

**Unblock action for execution agent:** Await availability of dedicated test authentication; then execute only the two existing isolated E2E scenarios, report sanitized Codex JSONL + trace correlation, record exact pass/fail/skip and reachable commit SHA, and resubmit for main-agent review. Do not reveal authentication contents in the report or chat.


### Round 7 review — 2026-10-10 — first authenticated E2E attempt

**Verdict:** CHANGES_REQUESTED — CLI invocation compatibility; E2E still UNVERIFIED  
**Review basis:** User-provided Windows PowerShell/pytest output from Python 3.12.9, pytest 8.4.2, running `-k "real_codex_cli_pretooluse"` in the AgentContract workspace. No tokens/auth contents were uploaded. Reported test-only auth login succeeded and the test credential path exists.

**Live E2E test results:** `2 failed, 7 deselected in 1.33s`. Both `test_real_codex_cli_pretooluse_allow_completed` and `test_real_codex_cli_pretooluse_deny_blocked` failed at the same CLI option-parser boundary, `res.returncode == 2`, **before any AgentContract ALLOW/DENY runtime behavior was exercised**:

```
error: the argument '--sandbox <SANDBOX_MODE>' cannot be used with '--approve-for-me'
```

The `WARNING: ... could not create PATH aliases ... Refusing to create helper binaries under temporary dir ...` is a separate, currently non-fatal warning; do not change sandbox or users' global Codex settings as a workaround.

**Required minimal patch:** In the **two** real Codex CLI subprocess argument arrays in `tests/integrations/test_codex_cli.py`, remove the obsolete/incompatible `"--approve-for-me"` element; **retain** explicit `"--sandbox", "workspace-write"`, `"--dangerously-bypass-hook-trust"` only for the isolated test workspace with vetted project hooks, project-local `-C`, `--json`, isolated `CODEX_HOME` and `AGENTCONTRACT_SESSION_DIR`. Never use `--dangerously-bypass-approvals-and-sandbox` or `danger-full-access`. Codex CLI's documented non-interactive form is `codex exec --sandbox workspace-write`. If approval policy must be selected explicitly, verify support from the installed `codex exec --help` and use the supported `--ask-for-approval never` rather than `--approve-for-me`, but prioritize the simplest safe compatible argv.

**Regression and proof:** Add a deterministic assertion preventing incompatible approval flags on either E2E invocation; run local Python 3.12.9 offline suite, then re-run `python -m pytest tests/integrations/test_codex_cli.py -k "real_codex_cli_pretooluse" -vv -rs` with the *already independently supplied* dedicated test auth. Preserve sanitized stdout JSONL, stderr and trace evidence for actual ALLOW/Completed and DENY/Blocked. If any new runtime failure appears, document it precisely and do not declare success based on static tests or hook stderr alone. Do not paste auth or API tokens into report.

**Disposition:** Dedicated auth prerequisite is now available in the user's local test environment, but test harness commands fail before agent runtime. Change task status from BLOCKED to CHANGES_REQUESTED pending CLI flag fix and live retest. No product merge, no TASK-013, no global Codex changes.


### Round 8 review — 2026-10-10 — authenticated E2E reaches Codex but Windows execution policy blocks tools

**Verdict:** BLOCKED — Windows sandbox/tool-process preflight and project-hook activation unverified; NOT ACCEPTED.  
**Reviewed branch/report HEAD:** `98ae1a28a7907499eff263cc6526f6546187e2ca`  
**Evidence:** User-provided native Windows PowerShell pytest output for Python 3.12.9, 2 failed / 8 deselected in 32.03s. This is actual opt-in authenticated Codex CLI invocation evidence, not a passing live E2E.

**ALLOW failure:** Prior `--approve-for-me` conflict is resolved. Codex produces JSONL thread/turn events and connects to the model, but `Get-Content -LiteralPath probe.txt` fails **before the child shell starts**, with `codex_core::tools::router: exec_command failed: CreateProcess ... rejected: blocked by policy`. Codex exits 0 and emits an agent message saying the environment blocked the command; `probe_content` is absent. This is NOT evidence of SpecGuard rejecting a compliant action. It is a tool execution policy/sandbox issue. A separate warning reports inability to create PATH aliases because test `CODEX_HOME` is beneath Windows TEMP; possible environment contributor, not established root cause.

**DENY failure:** Codex subprocess completes sufficiently to reach the test's later assertion, but `deny_proj/.agentcontract/sessions` **does not exist**. The test did install project-local `.codex/hooks.json`; nevertheless installation alone does not demonstrate that Codex loaded/called the hook. Because no Guard trace exists, neither a protected write attempt nor Guard BLOCK nor runtime hook DENY can be established. The protected file remaining unchanged is insufficient: no tool execution/hook activation has been proven.

**Likely preflight/configuration issue, not yet proven:** Current tests create a fresh `CODEX_HOME` inside `tmp_path` and copy only opt-in test `auth.json`; they do not configure the Windows native sandbox backend. OpenAI Codex configuration documents `windows.sandbox="elevated"` (Windows sandbox implementation), separately from the bounded `--sandbox workspace-write` filesystem permission mode. Public native Windows Codex reports describe identical `CreateProcess ... blocked by policy` on an isolated home without this selector, though Store/MSIX PowerShell launch restrictions are another possibility. These are hypotheses pending a controlled A/B run, not an established diagnosis of this exact machine.

**Required next diagnostics (no security bypass):**
1. In the **existing test-only CODEX_HOME**, establish executable/CLI version and effective native Windows sandbox backend. Perform a non-model sandbox smoke probe for a harmless `cmd.exe /c echo` and then an isolated read-only PowerShell probe; compare with/without the explicit `-c 'windows.sandbox="elevated"'` override, retaining bounded workspace-write and all Windows security controls. If the CLI syntax differs, inspect its `sandbox --help`; do not fall back to `danger-full-access`.
2. Examine project-hook activation only inside the synthetic project: verify Codex recognizes project `.codex/hooks.json`, project trust rules, that the `python -m agentcontract.integrations.codex.hooks` command is executable in the sandbox and the injected `AGENTCONTRACT_SESSION_DIR` reaches the handler. Separate direct hook smoke tests from Codex-dispatched hook tests; do not manufacture trace evidence.
3. Investigate the warning about temporary `CODEX_HOME` helper aliases. If the actual sandbox requires a CODEX_HOME outside Windows TEMP, create a per-test disposable directory under a dedicated `%LOCALAPPDATA%/AgentContract/` subtree with rigorous `try/finally` cleanup; never alter the personal home.
4. Make preflight failure clearly distinguish Windows policy rejection/hook not loaded from a product ALLOW/DENY protocol failure. Do not treat `res.returncode==0`, an agent final message, protected checksum stability, or absence of a session as successful Guard evidence.
5. Only after harmless shell and genuine session hook preflight pass, rerun isolated ALLOW/Completed and DENY/Blocked E2E with the dedicated test credentials; capture sanitized Codex JSONL and linked Guard trace. No token/auth contents in reports.

**Scope boundary:** Do not relax `--sandbox workspace-write`, switch to `danger-full-access`/`--dangerously-bypass-approvals-and-sandbox`, copy personal `~/.codex/auth.json`, modify global Codex trust/config, or merge product to `main`. TASK-012 remains sole active task. Review decision is BLOCKED pending safe Windows environment + hook-dispatch preflight evidence; no TASK-013.


#### Round 8 diagnostic addendum — 2026-10-10 (Windows sandbox underlying cause isolated)

User-provided test-only CODEX_HOME sandbox log identifies the **fatal** issue precisely:

```
runtime read/execute validation failed:
...\OpenAI\Codex\runtimes\cua_node\3dd31cfff853001c\bin\node_repl.exe:
open ACL target for root-only update: another process is using this file (os error 32)
setup refresh completed with errors
```

`codex doctor --json` reports `sandbox.helpers=ok` only for readable configuration; its details include `sandbox backend=disabled`, not a successful elevated Windows sandbox run. `codex-cli 0.162.0`. Both `codex -c 'windows.sandbox="elevated"' sandbox -- cmd /d /c echo ...` and read-only pwsh smoke fail before starting a child process. Running processes observed: multiple Codex, `codex-computer-use-swift`, Windows sandbox service and 6 `node_repl`; **actual blocking handle holder not yet identified**. A separate user-profile read-ACE sharing violation is logged as nonfatal.

Upstream matching bug reports (Oct 7–9, 2026): https://github.com/openai/codex/issues/52389 and https://github.com/openai/codex/issues/52501 describe `cua_node\3dd31cfff853001c\bin\node_repl.exe` sharing violations during root-only ACL update. Some reports reproduce after restarting; do not assume a reboot alone fixes it.

**Isolation/safety concern:** The same test HOME logs `granting read ACE` for unrelated real user directories (`.pi`, `.slock`, `.qoder`, etc.). This is an ACL-changing side effect of elevated Windows sandbox setup on the *normal user profile* despite use of a separate `CODEX_HOME`, conflicting with the project's zero unrelated side-effects goal. Do not repeat elevated initialization on the normal profile or reset/take ownership of global ACLs. Do not forcibly kill other Codex processes or delete/rename the CUA runtime. Prefer a disposable Windows VM or dedicated OS user/profile for sandbox preflight, and close relevant sessions normally first. `BLOCKED` remains correct; project ALLOW/DENY is neither vindicated nor disproven by this external Windows helper failure.

Safe next step: user saves active Codex work, exits Desktop/VSCode integration/other CLI normally, runs read-only process inspection for `node_repl.exe` and associated parents (no global kill); if still blocked, treat as upstream environmental blocker pending fixed Codex build or separate test OS profile. Resume authenticated bounded real E2E only after clean shell and hook dispatch work in an isolated environment. Preserve sanitized logs; never alter user-global Codex auth/config or weaken sandbox.

### Round 9 main-agent scope reset — 2026-10-10

**Verdict: CHANGES_REQUESTED.** User rejects VM, separate Windows login, restarting/stopping unrelated Codex, or invasive Windows sandbox preparation as prerequisites. Round 8 recommendations of these as normal workflow are **superseded**. Real Codex ALLOW/DENY E2E remains UNVERIFIED, not accepted.

**Mandatory product contract:**
1. Normal installation and use on the existing Windows account, Python 3.12.9, and ordinary Codex CLI/Desktop. No VM, separate Windows identity, new Codex identity, admin shell, stopping other active Codex sessions, or test-only authentication as a normal user requirement.
2. Install/status/uninstall are idempotent, reversible and limited to the explicitly selected project. Preserve foreign hooks and all other Codex workspaces. Never modify personal ~/.codex, global CODEX_HOME, authentication, approval/trust, plugins, shell profile, PATH, shared runtimes, user-profile ACLs or unrelated processes. Do not terminate codex/node_repl or run ACL reset/takeown.
3. Never automatically configure or invoke Windows native sandbox elevated/unelevated provisioning, bypass sandbox, or use danger-full-access as a workaround. The observed sandbox helper touches unrelated real-profile ACEs even with isolated CODEX_HOME. AgentContract can guarantee its own actions, NOT internal side effects of a particular upstream Codex build; if those would breach this contract, report UPSTREAM_ENV_BLOCKED without trying risky recovery.
4. Deliver one simple default, offline, no-login/no-network/no-LLM-cost/no-ACL/no-other-workspace doctor or smoke workflow. Distinguish installed hooks, actually invoked hooks, Guard decisions, and runtime enforcement; absent trace or Codex CreateProcess blocked-by-policy must not pass.
5. Keep real Codex ALLOW/Completed plus DENY/Blocked as a separate optional opt-in acceptance gate. Allow dedicated test-only auth only in explicit QA; skip safely on upstream sandbox problems and accurately label LIVE E2E UNVERIFIED. No machine-wide cleanup or interference. Add regression checks proving no global mutations or unsafe flag fallback.

**Executor action:** On same TASK-012 branch, audit integration and test launcher for Windows sandbox side effects and global mutations. Implement nonintrusive default smoke/doctor plus project-local isolation regressions, safe preflight that does not trigger unsafe provisioning, and concise user instructions. Keep production SpecGuard ALLOW/DENY semantics. Run Python 3.12.9 offline suite, report exact results and remaining external E2E blocker; commit/push. No product merge or TASK-013.

**Scope note:** A separate VM/OS account may be useful for upstream maintainer investigation but MUST NOT be an AgentContract requirement or recommended normal-user workaround.
