# TASK-011 — Codex Configuration Isolation & Zero External Side Effects

**Status:** CHANGES_REQUESTED  
**Milestone:** M6 — Codex Integration Operational Safety  
**Owner:** Execution agent  
**Work branch:** `task/TASK-011-codex-isolation`  
**Main-agent review:** CHANGES_REQUESTED — round 2

## Objective

Ensure AgentContract's project integration, plugin packaging, installer, test suite, and demo workflows have **zero unexpected effects on Codex outside the explicitly selected workspace**, whether the user runs Codex CLI or Codex desktop.

This is a hard boundary: AgentContract should **not** install, enable, trust, register, mutate, or remove user-global Codex hooks/plugins/marketplaces/settings, or alter unrelated workspaces. Only an explicit user action may enable a project-scoped integration. Do not globally disable other Codex hooks/plugins.

### Grounded current defects

1. `tests/integrations/test_codex_plugin.py::test_real_codex_plugin_marketplace_discovery_and_install_smoke` calls real `codex plugin marketplace add`, `codex plugin add`, `codex plugin remove agentcontract`, and marketplace removal with the inherited process environment. This can touch the user's shared `~/.codex` and can also remove a pre-existing user plugin. Running `pytest` must not do that.
2. `src/agentcontract/integrations/codex/cli.py::install_hooks` currently overwrites a pre-existing non-AgentContract `.codex/hooks.json`, backing it up to one `.bak` file. This can discard other project's hooks, and uninstall can replace/delete an entire file. Both installation and removal must be scoped and lossless.
3. `status_hooks()` inspects project-local `.codex/hooks.json` only; it must not imply there is no separately enabled user/plugin hook source.
4. The tracked `fixtures/real_codex_acceptance/.codex/hooks.json` and potentially historical fixture state must not be silently installed into the user's global Codex environment; tests and docs should make the workspace boundary explicit.

## Required implementation

### A. Test isolation (non-negotiable)

- Run any subprocess which changes Codex marketplace, plugin, trust or config state against a **temporary isolated CODEX_HOME** and test-only local marketplace. Never inherit the user's default Codex home for such mutation.
- If installed Codex cannot honor isolated `CODEX_HOME` or isolation cannot be verified, **skip/fail safely**, never fallback to the real user environment.
- Do not copy real user auth/config/hooks/trust databases into this testing home by default; tests of plugin discovery/install should be authentication-free.
- Each test cleans up only resources it created, including on assertion failure; do not use global `codex plugin remove agentcontract` outside isolated home.
- Repeat test executions must not change `%USERPROFILE%\.codex\config.toml`, `hooks.json`, marketplace state, plugin state, approval/trust state, or any external workspace.
- Validate this both for the full `python -m pytest` suite and for targeted plugin tests, on Windows / Python 3.12.9. Avoid changing Codex itself or modifying its global environment variables persistently.

### B. Project-scoped installer/uninstaller only

- `agentcontract codex install --project <dir>` modifies **only** that directory's intended `.codex` configuration.
- If the project already contains hooks, merge only AgentContract-owned entries rather than replacing unrelated hooks. Preserve the order/structure of all foreign entries. Idempotent installation must not multiply hooks.
- `uninstall --project <dir>` removes only AgentContract-owned hook entries. Never delete unrelated entries or replace them with a stale `.bak` snapshot. Use atomic file writes and safe recovery for invalid pre-existing files.
- Reject implicit global or ambiguous target path actions where appropriate; don't write `~/.codex` or its user hooks/plugin configuration.
- Installer, status, and uninstaller must be compatible with both CLI and Codex desktop reading project settings. Do not create global auto-enabled plugins or broad trust grants.

### C. Opt-in plugin handling and diagnostics

- Plugin marketplace samples are **manual opt-in** only; no install, uninstall, auto-enable, or trust grant of AgentContract at user/global scope as a side effect of importing, installing package or running standard pytest/demo.
- `codex status --project` should clearly distinguish project-local hook installation from other possible user/plugin sources; avoid claiming global hooks are absent when not checked.
- Add a non-destructive diagnostic/documented `audit` workflow (or extend status), optionally read-only checks of global Codex hooks/config/plugins without exposing keys, reporting whether AgentContract might affect external workspaces.
- Document **surgical cleanup of historical residual AgentContract plugin/marketplace registrations** from user's normal Codex home with inspection-before-removal. Never remove other plugins or edit unrelated global configuration.

### D. E2E acceptance and regression tests

Must cover:
1. A temporary project with no hooks: install, use, uninstall only affects that project.
2. A project with non-AgentContract hooks: install merges, idempotence, uninstall restores original content semantically.
3. An existing invalid hooks file: explicit safe failure without overwriting.
4. Two sibling workspaces, only A opted in: hooks never activate in B; verify project scope under both Codex CLI and desktop assumptions.
5. Isolated Codex plugin marketplace add/install/list/remove succeeds using test-only `CODEX_HOME`, without altering the normal home.
6. Importing AgentContract and standard test suite do not globally register hooks, plugins or marketplaces.
7. Explicit read-only pre/post snapshots or equivalent proof that normal user `CODEX_HOME` files/plugin state were untouched. The test may not mutate a real home to prove cleanup.
8. No test runner or example changes the global model/provider/sandbox approval configuration.
9. Python 3.12.9 full regression; real Codex project-only Guard / EvidenceGate acceptance remains functional.
10. Manual Codex desktop checklist verifying external projects unaffected and no new AgentContract trust prompts. If desktop cannot be automated, report that as MANUAL/UNVERIFIED, not passed.

### Authority and constraints

- Respect `AGENTS.md` main-agent/executor workflow. Only implement this task on `task/TASK-011-codex-isolation`.
- Do not modify real `%USERPROFILE%\.codex` or any user's machine-global Codex configuration in test procedures.
- Never call `codex plugin remove agentcontract` against a non-isolated home during tests; this risks deleting a real user-installed plugin.
- Do not require users to switch off all Codex hooks globally; unrelated hooks/plugins must remain operational.
- Do not perform automatic cleanup of historical user-global entries; give a safe, opt-in, selective procedure.
- Preserve TASK-010 behavior and ensure all existing test coverage remains green.

Official references:
- https://developers.openai.com/de-DE/docs/hooks
- https://developers.openai.com/zh-Hans/docs/config-file/config-basic
- https://developers.openai.com/plugins/build/plugins
- https://github.com/openai/codex/blob/main/codex-rs/cli/tests/marketplace_add.rs (isolated CODEX_HOME in upstream CLI tests)

## Executor Report

> Execution agent fills this section.

**Implementation summary (Round 2 Review Blocker Fixes):**
- **Blocker 1 (Project-Local Symlink / Junction Boundary Escape Rejection):**
  - Added `_validate_project_contained_path` and `_get_forbidden_codex_homes` in `src/agentcontract/integrations/codex/cli.py`.
  - Prior to any read, write, modify, or unlink operation in `install_hooks`, `uninstall_hooks`, and `status_hooks`, both `.codex` and `hooks.json` are canonically resolved and checked:
    - Path must strictly remain within canonical `project_root` (`target.is_relative_to(project_root)`).
    - Cannot point to system roots, user home (`Path.home()`), or user's global `CODEX_HOME` / `~/.codex`.
    - If a junction, symlink, or reparse point escapes the canonical project root boundary or resolves to a forbidden destination, operations immediately abort with exit code 1 without writing or unlinking external files.
    - `audit_hooks` inspects project `.codex` containment and reports `[ESCAPE_DETECTED]` / `[SUSPICIOUS / ESCAPE DETECTED]` if boundary escape occurs.
  - Added regression test `test_junction_symlink_boundary_escape_rejection` in `tests/integrations/test_codex_isolation.py` verifying that junction `.codex` pointing to an external directory is rejected on install, uninstall, and status with 0 changes to the external directory.
- **Blocker 2 (Lossless Foreign JSON and Empty Foreign Arrays Preservation):**
  - Refactored `uninstall_hooks` in `src/agentcontract/integrations/codex/cli.py` to perform an ownership-targeted, lossless edit of the existing JSON structure rather than rebuilding only nonempty events.
  - Foreign event keys, unknown top-level keys, metadata (such as `schemaVersion`, `note`), group metadata, and empty foreign event arrays (e.g. `PostToolUse: []`) are strictly preserved.
  - `.codex/hooks.json` is unlinked **only** if the file was entirely AgentContract-generated and has zero foreign/unrelated content (no top-level metadata, no foreign events, no remaining handlers).
  - Added regression test `test_uninstall_lossless_wrapped_foreign_config_with_empty_arrays` verifying the exact reproduction case and multi-event configs.
- **Blocker 3 (Audit Precision & Targeted Non-Destructive Cleanup Guidance):**
  - Updated `audit_hooks` in `src/agentcontract/integrations/codex/cli.py`:
    - Replaced blanket `[CLEAN] Zero External Side Effects Confirmed` with scoped `[PROJECT_SCOPED_ONLY]`.
    - Explicitly reports inspection coverage and marks Desktop GUI state, system runtime memory, and uninspected external paths as `UNVERIFIED`.
    - For stale config-only entries in `config.toml` without active cached plugins, recommends safe, backed-up exact-section removal (`Remove [plugins."<plugin>"]`) rather than broad `codex plugin remove agentcontract`.
    - Updated `docs/integrations/codex.md` and synthetic audit tests to reflect the precise scoped output.
- **Regression/Test Guard (Guaranteed Post-Test Environment Integrity Verification):**
  - Enhanced `tests/conftest.py` with `try ... finally` around `yield` in both function-level `guard_user_codex_home_per_test` and session-level `guard_user_codex_home_isolation` fixtures.
  - Even if a test raises an `AssertionError` or unhandled exception, teardown verification of real user `~/.codex` hashes and directory contents is guaranteed to run.
  - Moved read-only real user Codex verification in `tests/integrations/test_codex_plugin.py` into the `finally:` block of `test_real_codex_plugin_isolated_workflow`.
  - Added regression test `test_environment_integrity_guard_resilience` in `tests/integrations/test_codex_isolation.py`.

**Files changed:**
- `src/agentcontract/integrations/codex/cli.py`
- `tests/conftest.py`
- `tests/integrations/test_codex_isolation.py`
- `tests/integrations/test_codex_plugin.py`
- `docs/integrations/codex.md`
- `.agent/tasks/TASK-011.md`

**Tests/checks run and results:**
- Full pytest suite on Python 3.12.9: **355 passed, 0 failed in 11.38s** (`python -m pytest`).
- `test_codex_isolation.py`: 12 passed in 1.06s.
- `test_codex_cli.py`: 2 passed in 0.51s.
- `test_codex_plugin.py`: 3 passed in 1.35s (under isolated `CODEX_HOME` with in-place hash integrity checks and `finally:` teardown).
- Real CLI `agentcontract codex audit` run verified against actual user home: correctly detected residual cache registration and emitted targeted guidance without false `CLEAN` or broad plugin deletion claims.
- In-place SHA-256 file hashing confirmed real user `~/.codex` files untouched.

**Known limitations:**
- Headless automated tests cover CLI hooks and configuration isolation. Visual GUI dialogs in Codex Desktop cannot be headlessly automated and are tracked as `MANUAL/UNVERIFIED` in accordance with the task specification.

**Commit SHA:**
- Implementation: `994ea60b9dc076263ae78d4beea6c3bf045ca35e`

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — round 2 (remaining no-cross-workspace guarantees)

**Implementation reviewed:** `a33562d570e69bf8b300204ccfa49fbfaa7369b7`  
**Branch head/report reviewed:** `5171c446d836576d820f3346fe309ffe05ab87eb`

**Progress accepted:** All four round-1 issues are materially addressed in source: mixed groups filter individual child handlers; invalid hook structures are rejected without overwrites; `tomllib` audit catches AgentContract entries in global `config.toml`; filesystem roots use typed Path comparisons. Executor reports **352 passed, 0 failed**; tests and real Windows Codex behavior are executor-reported, not independently replayed by main agent.

### BLOCKER 1 — project-local path may escape through .codex junction/symlink

`install_hooks()` validates only `proj = Path(project_dir).resolve()`, then writes `proj / ".codex" / "hooks.json"` without resolving/checking the **actual destination**. Likewise `uninstall_hooks()` follows the same unchecked `.codex` directory path. On Windows an otherwise innocent test project may contain a directory junction `project\.codex` targeting `%USERPROFILE%\.codex`. Installing AgentContract into that project will then write the user's *global* `hooks.json`. Uninstall may modify/remove that global file. This directly violates the user's explicit non-interference requirement.

**Fix:** validate the canonical destination directory/path before writes/deletes; reject project-local `.codex` symlinks/junctions/reparse points that escape the canonical project root, including real user Codex home and sibling projects. Prefer fail-safe no-op with explicit error on unresolvable, redirected, or suspicious paths. Add tests with a temporary external target and a junction/symlink where supported; never point a regression at the user's real Codex home. Check both install and uninstall (and make status/audit non-misleading).

### BLOCKER 2 — uninstall loses unrelated top-level fields and empty foreign event arrays

`uninstall_hooks()` constructs `remaining_events` from nonempty hook lists and then removes the entire `hooks.json` when `remaining_events` is empty. This ignores unrelated top-level metadata and loses existing empty event arrays:

Reproduction using a valid wrapped config:

```json
{
  "schemaVersion": 1,
  "note": "foreign metadata",
  "hooks": {
    "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "python -m agentcontract.integrations.codex.hooks PreToolUse"}]}],
    "PostToolUse": []
  }
}
```

Current uninstall removes `PreToolUse` and drops `PostToolUse: []`, then deletes the **entire file**, losing both `schemaVersion` and `note`. With other foreign events, the file is retained but empty arrays still disappear.

**Fix:** perform an ownership-targeted, lossless edit to the existing JSON structure rather than rebuilding only nonempty events. Preserve top-level metadata, unknown keys, all foreign event keys/arrays (including empty arrays), group metadata and order. Delete the file only if it was entirely AgentContract-generated and has no unrelated content; otherwise preserve a structurally valid config. Add a complete semantic before/after regression for a wrapped config with metadata and empty foreign arrays.

### BLOCKER 3 — audit/cleanup still overstate certainty and suggest unsafe broad removal

`audit_hooks()` prints `[CLEAN] Zero External Side Effects Confirmed` and `AgentContract ... does not affect other ... Desktop` after scanning a limited subset of global state; this is not a proof of zero side effects or desktop-wide inactivity. Additionally, if it discovers only stale `[plugins."agentcontract@..."]` entries but the plugin is absent from `codex plugin list`, it recommends broad `codex plugin remove agentcontract`; this can be irrelevant or remove a different user-installed AgentContract plugin. The user's actual history included such stale-but-enabled config entries.

**Fix:** distinguish "no known AgentContract global hooks/plugin entries found in inspected sources" from an absolute guarantee; report inspection coverage and skipped/unreadable sources as `UNVERIFIED/INCOMPLETE`. For stale config-only entries, recommend inspected, backed-up, exact-section removal rather than broad plugin deletion. Never automatically mutate global home. Update status/documentation and synthetic audit test expectations accordingly.

### Regression/test guard

The plugin smoke test's full user-home post-snapshot check is after a `try/finally` and is **skipped if any test assertion raises**. Move the read-only integrity check into a teardown/finally scope, or use a robust fixture to ensure checks run on failed tests too. Its `CODEX_HOME` subprocess override is a good improvement and must remain. Compare relevant in-place contents, not only top-level filenames. No forced global plugin removal.

### Acceptance

- Python 3.12.9 full pytest with isolated `CODEX_HOME`; executor should report exact pass/skip counts.
- Demonstrate local project A cannot escape into B or global via directory junction/symlink; zero modifications to B.
- Demonstrate install/uninstall preserves foreign hooks **and** unrelated JSON metadata, including empty arrays.
- Audit never claims broad Desktop/CLI isolation as proven by incomplete static inspection; cleanup instructions specific and non-destructive.
- Keep real Codex project-only integration working. Desktop GUI verification must remain `MANUAL/UNVERIFIED` unless actually performed.
- Update Executor Report with final implementation SHA; commit/push on `task/TASK-011-codex-isolation`, do not merge to main.

No other feature scope expansion.

