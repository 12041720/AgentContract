# TASK-011 — Codex Configuration Isolation & Zero External Side Effects

**Status:** ACCEPTED  
**Milestone:** M6 — Codex Integration Operational Safety  
**Owner:** Execution agent  
**Work branch:** `task/TASK-011-codex-isolation`  
**Main-agent review:** ACCEPTED — round 3; selectively integrated to main

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

**Verdict:** ACCEPTED — round 3 (2026-10-09)
**Final executor implementation:** `994ea60b9dc076263ae78d4beea6c3bf045ca35e`
**Executor report head inspected:** `29addcc3debadfd1b7a459776392305812a54588`
**Reviewed branch code + doc correction:** `f783f93e54761a5acb86a81f03f36e518a62abf3`
**Selective integration into main:** `a8343521416cbe97a257a4c06f19730c3265ee60`

### Acceptance findings

- Plugin/marketplace mutation test subprocesses use temporary, explicitly set CODEX_HOME for all add/list/install/remove commands, with no unguarded global plugin removal in automated tests.
- Project hooks install/status/uninstall validate canonical destinations against project-root containment. Regressions cover Windows Junction or POSIX symlink redirect into an external sibling directory and check external state unchanged.
- Installer rejects invalid JSON and malformed hook structures; uninstall removes AgentContract-owned handlers without deleting third-party handlers, unrelated top-level metadata, or empty foreign event arrays.
- Audit reads global config.toml, selected global hook/plugin sources, reports residual entries and inspection coverage, and avoids claims of complete external Desktop or CLI verification. No automatic user-global edits.
- Function- and session-scope pytest guards and plugin-test finally clause check relevant user-global file hashes even if tests fail.
- Main-agent editorial update to docs removes unconditional broad plugin removal advice and marks Desktop GUI manual smoke checklist unchecked MANUAL/UNVERIFIED.

### Verification and limits

Executor reports **355 passed, 0 failed** in full pytest (Windows Python 3.12.9), including 12 Codex isolation tests. Main agent independently inspected source, tests, docs, and repo diff; no CI status was available. Independent clone/test attempt in main-agent container failed due to github.com DNS unavailability, and that environment's Python is 3.13.5, not the required 3.12.9. Test results are executor-reported, not independently rerun. Desktop GUI validation remains MANUAL/UNVERIFIED.

### Governance

Six reviewed product, documentation, and test files selectively integrated to main, preserving authoritative .agent history. No new task automatically activated. TASK-011 and M6 accepted.

**Disposition:** ACCEPTED.
