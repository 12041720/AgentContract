# TASK-011 — Codex Configuration Isolation & Zero External Side Effects

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M6 — Codex Integration Operational Safety  
**Owner:** Execution agent  
**Work branch:** `task/TASK-011-codex-isolation`  
**Main-agent review:** pending

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

**Implementation summary:**
- **Part A (Test Isolation & Zero User Home Mutation):**
  - Updated `tests/integrations/test_codex_plugin.py::test_real_codex_plugin_marketplace_discovery_and_install_smoke` to run against an isolated `CODEX_HOME` (`tmp_path / "isolated_codex_home"`).
  - Verified that all `codex plugin marketplace add/list/remove` and `codex plugin add/list/remove` subprocesses receive `env=dict(os.environ, CODEX_HOME=str(isolated_codex_home))`.
  - Added pre/post snapshot checks ensuring user's real `Path.home() / ".codex"` is completely untouched.
  - Added session-scoped autouse safeguard fixture `guard_user_codex_home_isolation` in `tests/conftest.py` that asserts no AgentContract artifacts, `.bak` files, or test marketplaces leaked into the user's real `~/.codex` during any pytest session.
- **Part B (Project-Scoped Installer/Uninstaller with Lossless Merging & Atomic Writes):**
  - Refactored `src/agentcontract/integrations/codex/cli.py`:
    - `install_hooks`: Rejects dangerous system root or user home directory targets. Checks for existing `hooks.json` syntax; safely refuses to overwrite if corrupted. Losslessly merges only AgentContract-owned entries (`_is_agentcontract_hook_entry`), preserving all foreign/third-party hooks, their order, and structure. Idempotent on repeat runs. Uses atomic file writes (`_atomic_write_json`) via temp files and `os.replace` to prevent partial write risks.
    - `uninstall_hooks`: Selectively removes ONLY AgentContract-owned entries. If foreign hooks remain in the project, preserves them with atomic write; unlinks `hooks.json` only if all entries belonged to AgentContract. Does not restore stale `.bak` files.
    - `status_hooks`: Explicitly reports project-local scope boundary (`Project-local only (zero effect on global ~/.codex)`) and counts foreign vs AgentContract hook entries.
- **Part C (Opt-In Diagnostic Audit & Documentation):**
  - Implemented `agentcontract codex audit [--project <dir>]` in `cli.py`: performs non-destructive read-only checks of the project-local hooks and user global Codex home (`~/.codex`). Reports an isolation assessment and gives surgical manual cleanup commands (`codex plugin remove agentcontract`) without automatically mutating global state.
  - Updated `docs/integrations/codex.md` with zero external side effects architecture, audit command, surgical cleanup procedures, and manual Codex Desktop checklist.
- **Part D (Comprehensive Isolation Regressions):**
  - Added `tests/integrations/test_codex_isolation.py` with 8 comprehensive tests covering:
    1. Single-project lifecycle without affecting sibling projects (`test_temporary_project_install_status_uninstall_isolation`).
    2. Merging foreign hooks, idempotence, and exact semantic restoration upon uninstall (`test_merge_and_preserve_foreign_hooks`).
    3. Safe failure without overwriting or deleting corrupted hooks files (`test_invalid_hooks_file_safe_failure`).
    4. Rejection of system root and home directory targets (`test_dangerous_root_and_home_targets_rejected`).
    5. Sibling workspaces isolation (`test_sibling_workspaces_isolation`).
    6. Read-only non-destructive audit command verification (`test_audit_command_read_only`).
    7. Import and standard suite zero global side effects (`test_import_and_test_suite_zero_global_effects`).
    8. CLI main integration for audit command (`test_cli_subcommand_audit_integration`).

**Files changed:**
- `src/agentcontract/integrations/codex/cli.py`
- `src/agentcontract/cli.py`
- `docs/integrations/codex.md`
- `tests/conftest.py`
- `tests/integrations/test_codex_plugin.py`
- `tests/integrations/test_codex_isolation.py`
- `.agent/tasks/TASK-011.md`

**Tests/checks run and results:**
- Full pytest suite on Python 3.12.9: **351 passed, 0 failed in 8.80s** (`python -m pytest`).
- `test_codex_isolation.py`: 8 passed in 0.56s.
- `test_codex_cli.py`: 2 passed in 1.65s.
- `test_codex_plugin.py`: 3 passed in 1.45s (under isolated `CODEX_HOME`).
- Direct CLI invocation `python -m agentcontract.cli codex audit` verified read-only and accurate.
- Real user `~/.codex` verified untouched by test suite.

**Known limitations:**
- Headless automated tests cover CLI hooks and configuration isolation. Visual GUI dialogs in Codex Desktop cannot be headlessly automated and are tracked as `MANUAL/UNVERIFIED` in accordance with the task specification.

**Commit SHA:**
- Implementation: `1de707eefb514f0ab35f3daf349f0103db1a7301`

## Main Agent Review

> Main agent only.

Pending.
