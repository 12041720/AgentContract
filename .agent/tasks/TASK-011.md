# TASK-011 — Codex Configuration Isolation & Zero External Side Effects

**Status:** CHANGES_REQUESTED  
**Milestone:** M6 — Codex Integration Operational Safety  
**Owner:** Execution agent  
**Work branch:** `task/TASK-011-codex-isolation`  
**Main-agent review:** CHANGES_REQUESTED — round 1

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

**Implementation summary (Round 1 Review Blocker Fixes):**
- **Blocker 1 (Mixed Hook Group Handler Preservation on Uninstall):**
  - Refactored `uninstall_hooks` in `src/agentcontract/integrations/codex/cli.py` to filter individual hook handlers using `_is_agentcontract_handler` rather than dropping the whole matcher group entry.
  - When an entry contains a list of `"hooks"`, only handlers containing `AGENTCONTRACT_HOOK_MARKER` are removed. The matcher group, `"matcher"`, and all foreign/third-party handlers (such as `node scripts/third_party_guard.js`) are preserved intact. A group is only dropped if its handlers list becomes empty and has no foreign metadata.
  - Added regression test `test_mixed_matcher_group_uninstall_preserves_third_party_handlers` in `tests/integrations/test_codex_isolation.py`.
- **Blocker 2 (Strict Structural Validation without Overwriting Malformed Configurations):**
  - Added `_validate_hooks_json_structure` in `src/agentcontract/integrations/codex/cli.py` to enforce strict schema shape:
    - `"hooks"` key (if present) must be a dictionary.
    - Each event value must be a list of dictionaries.
    - Each entry's `"hooks"` property (if present) must be a list of handler dictionaries.
  - If any unexpected shape is detected (e.g. `{"hooks": []}`, `{"hooks": {"PreToolUse": {"hooks": []}}}`, nulls, or strings), `install_hooks` and `uninstall_hooks` exit with code 1, emit descriptive errors to stderr, and leave the original file bytes completely untouched.
  - Added regression test `test_malformed_hook_structures_rejected` covering 6 structural failure shapes with byte-for-byte unchanged file verification.
- **Blocker 3 (Audit Inspection of config.toml & In-Place Mutation Detection):**
  - Implemented `_inspect_codex_config_toml` in `src/agentcontract/integrations/codex/cli.py` using Python 3.12's standard library `tomllib`. Safely inspects `[plugins]` and `[marketplaces]` sections in `config.toml` (under `CODEX_HOME` or user default) for AgentContract entries without exposing secrets.
  - Categorizes isolation assessment into `CLEAN`, `RESIDUAL`, or `UNVERIFIED/INCOMPLETE`. Detects residual enabled plugin entries (e.g. `[plugins."agentcontract@test_market_..."] enabled = true`) even when `plugins/cache` is empty.
  - Enhanced `tests/conftest.py` and `tests/integrations/test_codex_plugin.py` to record SHA-256 pre/post hashes of existing user configuration files (`config.toml`, `hooks.json`, `auth.json`) to detect in-place mutations.
  - Added regression tests `test_audit_detects_residual_config_toml_without_cache` and `test_audit_clean_synthetic_home`.
- **Blocker 4 (Typed Root-Path and Case-Normalized User Home Rejection):**
  - Updated `_is_forbidden_target_dir` in `src/agentcontract/integrations/codex/cli.py` with typed check `resolved == Path(resolved.anchor) or resolved.parent == resolved`, and case-normalized home comparison `os.path.normcase(str(resolved)) == os.path.normcase(str(Path.home().resolve()))`.
  - Added regression test `test_root_path_rejection` safely testing root-path rejection via mocked resolution without touching real filesystem roots.

**Files changed:**
- `src/agentcontract/integrations/codex/cli.py`
- `tests/conftest.py`
- `tests/integrations/test_codex_plugin.py`
- `tests/integrations/test_codex_isolation.py`
- `.agent/tasks/TASK-011.md`

**Tests/checks run and results:**
- Full pytest suite on Python 3.12.9: **352 passed, 0 failed in 7.74s** (`python -m pytest`).
- `test_codex_isolation.py`: 9 passed in 0.60s.
- `test_codex_cli.py`: 2 passed in 0.43s.
- `test_codex_plugin.py`: 3 passed in 1.33s (under isolated `CODEX_HOME` with in-place hash integrity checks).
- Direct CLI invocation `python -m agentcontract.cli codex audit` verified against real environment: correctly identified residual plugin cache entry without false `CLEAN` claim.
- In-place SHA-256 file hashing confirmed real user `~/.codex` files untouched.

**Known limitations:**
- Headless automated tests cover CLI hooks and configuration isolation. Visual GUI dialogs in Codex Desktop cannot be headlessly automated and are tracked as `MANUAL/UNVERIFIED` in accordance with the task specification.

**Commit SHA:**
- Implementation: `a33562d570e69bf8b300204ccfa49fbfaa7369b7`

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — round 1 (Codex isolation hardening)

**Implementation reviewed:** `1de707eefb514f0ab35f3daf349f0103db1a7301`  
**Branch head reviewed:** `74be048cc07d51b2a3b5b6df88296e7e48bf9085`

**Accepted progress:** Test plugin/marketplace mutation subprocesses now set an isolated temporary `CODEX_HOME`; project installer merges hooks instead of overwriting the entire valid foreign-hook file in the common case; an audit command and regressions exist. The executor reports 351 green tests on Python 3.12.9. This is execution-agent evidence, not independently rerun by main agent.

### BLOCKER 1 — mixed Hook groups lose third-party handlers during uninstall

`src/agentcontract/integrations/codex/cli.py::_is_agentcontract_hook_entry` returns true if **any child handler** within a matcher group belongs to AgentContract. `uninstall_hooks` then drops the **entire group**.

Concrete loss scenario:

```json
{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[
 {"type":"command","command":"python -m agentcontract.integrations.codex.hooks PreToolUse"},
 {"type":"command","command":"node scripts/third_party_guard.js"}
]}]}}
```

Uninstall destroys `third_party_guard.js`, violating isolation. **Fix:** remove only AgentContract-owned individual handlers; retain the original group and all unrelated handlers and metadata. Drop a group only if its own handler list becomes empty and no independent meaning/metadata needs preservation. Add exact semantic-preservation regression tests for mixed groups (also test idempotent install).

### BLOCKER 2 — existing malformed *structure* overwritten, despite valid JSON

`install_hooks` currently does `hooks_map[event] = []` when an existing event value is not a list, discarding foreign content. For a top-level `"hooks"` key that exists but is not an object, the code also falls back to `existing["hooks"] = {}` and overwrites that field.

**Fix:** for unknown/unsupported structural shapes, explicitly fail non-destructively and leave the original bytes intact. Reject malformed `hooks` root map, malformed event arrays, malformed handlers or unsafe partial shape; do not silently coerce. Add cases for `{"hooks": []}`, `{"hooks":{"PreToolUse":{"hooks":[]}}}`, and null/string values, with unchanged file verification.

### BLOCKER 3 — audit reports false global cleanliness, state-snapshot test misses in-place mutations

`audit_hooks` checks `~/.codex/hooks.json` and only a narrow plugin-cache path; it does **not** examine `~/.codex/config.toml` for `[plugins."agentcontract@test_market_..."] enabled = true` or other plugin/marketplace config. This was the *actual residual observed on user's machine*. The code can print `[PASSED] Zero External Side Effects Confirmed` even with seven globally enabled AgentContract test entries.

Additionally `tests/conftest.py` and the plugin smoke test compare only top-level directory entry names, which cannot detect **in-place modifications to existing config.toml, plugin registry or approval/trust files**. The current tests do not prove their stated zero-mutation guarantee.

**Fix:**
- Audit read-only relevant `config.toml` plugin/marketplace sections with safe TOML parser (`tomllib`), handling `CODEX_HOME` correctly, plus global hook sources; distinguish `CLEAN`, `RESIDUAL`, and `UNVERIFIED/INCOMPLETE` rather than making ungrounded blanket guarantees. Never expose secrets/config values.
- Regressions with temporary synthetic global Codex homes containing precisely the seven-style `agentcontract@...` enabled entries and zero cache entries; should **not** print `PASSED`.
- Validate isolated test provenance: assert test-created plugin marketplace and installation only under temporary CODEX_HOME. To assert unchanged real Codex state, compare relevant *existing file contents/hashes* or snapshots of controlled fake homes (not merely top-level names). Avoid legitimate concurrent user activity causing false positives. No mutation of real `~/.codex`.

### BLOCKER 4 — root-path rejection is a no-op on ordinary Path objects

`install_hooks()` currently uses `proj == proj.anchor`, but `proj` is a `Path` and `proj.anchor` is a `str`; a filesystem root such as `C:\\` is therefore not rejected by that comparison. The existing test checks only a fake user home and does not exercise a root path.

**Fix:** use `proj == Path(proj.anchor)` (or equivalent resolved typed comparison), make user-home checks robust to Windows case/normalization, and test root detection **without actually writing to a system root** (e.g. inject/mocking path resolution/creation).

### Final checks

- `python -m pytest` Python 3.12.9; test plugin mutation with isolated CODEX_HOME and no global state changes.
- Exact preservation of foreign handlers, event structure, order, and unrelated top-level fields after install/uninstall; invalid shapes never overwritten.
- Audit recognizes residual `enabled = true` `agentcontract@test_market` plugin config even when cache missing; no false `Zero External Side Effects Confirmed` claim.
- Project A opt-in does not activate AgentContract in B; CLI regression and manual desktop checklist clearly marked as MANUAL/UNVERIFIED if not executed.
- Update Executor Report with final implementation SHA; commit/push `task/TASK-011-codex-isolation`. **Do not merge main.**

No other features are requested.

