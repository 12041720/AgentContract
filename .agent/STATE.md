# Persistent Project State

> This file is authoritative. Read it before doing any work.

## Project

- Name: AgentContract
- Mission: Runtime constraint tracking and evidence-grounded completion verification for long-horizon tool-using agents.
- Stage: M7 Codex PreToolUse protocol compatibility review
- Architecture version: 0.1
- Default branch: `main`

## Current active task

- Task: **TASK-012 — Codex CLI PreToolUse Output Protocol Compatibility**
- Task file: `.agent/tasks/TASK-012.md`
- Work branch: `task/TASK-012-codex-pretooluse-compat`
- Status: **BLOCKED**
- Owner: Execution agent
- Main-agent review: Round 12 BLOCKED (offline fixes pass code review; real Codex ALLOW/DENY E2E unverified)
- Previous accepted milestone: TASK-011 / M6

## Main-agent checkpoint

- Repository initialized on 2026-09-22.
- Persistent main-agent/executor protocol established.
- High-level architecture fixed for v0.1.
- TASK-001 accepted after final hardening and integrated to `main` as `48a7ae1cc07025a400b11804c298c2970cfc5107`.
- TASK-002 accepted and integrated to `main` as `2c71b2509dc82a95a2c3ce298602811f549ac1ff`.
- TASK-003 accepted and integrated to `main` as `495b23b262d51e076ad2f6c36b81edba4169f4d4`.
- TASK-004 accepted and integrated to `main` as `f93c5f70e93e4d2ef8341c719dba66f951ed8e03`.
- TASK-005 accepted and integrated to `main` as `94ec3c32dc685528fa5265e11c8945b16fdbc6b4`.
- TASK-006 accepted and integrated to `main` as `cc61b75d34e75ea47ee2f289874a719bf4be247f`.
- TASK-007 accepted and integrated to `main` as `12dad52df4b2901905c2ea92c07f8a71d2934d7f`.
- TASK-008 accepted and integrated to `main` as `0469bf7a0204eba56aaa2fe44d65edfb63b8b4ac`.
- External adapters, OTLP bridge, and real OpenAI-compatible extraction quickstart are available.
- TASK-009 completed v0.1 packaging, evidence/claim grounding, and online provider acceptance.

## Current design decisions

1. Core logic is developed against the user's installed local Python **3.12.9** and remains vendor-neutral. Do not install alternate Python interpreters solely for compatibility testing.
2. Pydantic models are used at system boundaries and for durable domain state.
3. Constraint tracking and evidence verification are separate subsystems connected through shared provenance/trace identifiers.
4. Hard constraints must be enforceable without asking the same LLM that generated the action to self-police.
5. Verification has explicit states; unknown/unverified is distinct from false.
6. MVP targets coding/tool agents first but domain types must not hard-code Git or filesystem semantics.
7. Main-agent coordination is persisted under `.agent/`; chat history is not a source of truth.

## Review gate

The main agent will not mark v0.1 complete until TASK-009 satisfies its acceptance criteria and is reviewed.

## Resume instructions for the main agent

On a new session:
1. Read `AGENTS.md`.
2. Read this file.
3. Read the active task file.
4. Inspect changes/PR/commit produced by the execution agent.
5. Run or inspect tests where possible.
6. Write verdict to the task file and `.agent/REVIEW_LOG.md`.
7. Update this file and `.agent/TASKS.md`.
8. Activate exactly one next task unless parallel work is explicitly introduced.

## v0.1 completion checkpoint

- TASK-009 accepted and integrated to `main` as `6c24d9f749e0249a8a75da89effccbdcdb5c6e5e`.
- All TASK-001 through TASK-009 are accepted.
- Executor-reported full suite: 288 tests passed on Python 3.12.9.
- CLI/package/documentation and real OpenAI-compatible provider smoke path are complete for v0.1.
- No subsequent task is active by default.

## M5 completion checkpoint (2026-10-09)

- TASK-010 real Codex harness integration ACCEPTED and selectively integrated to `main` as `8b3d4ee1f7ad11991a04f72f83ba303387965623`.
- Product code includes real Codex lifecycle hooks, persisted session ledger/trace, SpecGuard tool interception and EvidenceGate stop verification.
- Executor-reported acceptance: 343 tests passed and real plugin-only Codex hook run with protected write DENY, unchanged file checksum and VERIFIED/UNVERIFIED claims.
- No active development task unless explicitly selected.

## M6 isolation hardening checkpoint (2026-10-09)

- TASK-011 activated after discovering that real Codex plugin marketplace tests use inherited user Codex configuration and uninstall by broad plugin name.
- Acceptance requirement: AgentContract project and tests must not modify user-global Codex plugin, hook, trust, approval, configuration, or unrelated workspaces (CLI or desktop).
- Run global-mutating integration tests only with isolated CODEX_HOME; scoped install/uninstall must preserve existing project hooks.

## M6 completion checkpoint (2026-10-09)

- TASK-011 Codex Configuration Isolation & Zero External Side Effects ACCEPTED after third-round review.
- Isolated Codex plugin mutation subprocesses with temporary CODEX_HOME; scoped hook install/uninstall preserves foreign hooks and metadata; rejected symlink/Junction escape destinations; audit reports limited inspection and stale global records without changing them.
- Selective product/test/docs integration to main: `a8343521416cbe97a257a4c06f19730c3265ee60`.
- Executor-reported Windows Python 3.12.9 regression: 355 passed, 0 failed. Main agent independently reviewed code/tests, but could not rerun tests (no GitHub DNS access in its container).
- Codex Desktop GUI isolation remains MANUAL/UNVERIFIED. No automatic global Codex cleanup or next task activated.

## M7 compatibility review checkpoint (2026-10-09)

- TASK-012 work branch created and evaluated by main agent. Production ALLOW-without-updatedInput now returns empty Hook output, DENY shape retained; unit-level behavior appears correct.
- Executor reports 358 passing pytest tests (Python 3.12.9); these were not independently rerun by main agent.
- Round 1 review CHANGES_REQUESTED because real CLI tests copy the user's global Codex auth.json, run unrestricted with --dangerously-bypass-approvals-and-sandbox, and do not robustly prove DENY was caused by a recorded SpecGuard block.
- Added subprocess fixture cwd isolation requirement to prevent repository-local .agentcontract state writes.
- Full findings in `.agent/tasks/TASK-012.md`. No production code merged and M7 not accepted.

## M7 round 3 checkpoint (2026-10-09)

- Reviewed executor implementation `1c4877a9` and report branch `9bb6a332`: explicit bounded sandbox requested; live online tests still skipped.
- Round 3 CHANGES_REQUESTED for authenticated test NameError, ineffective sandbox evidence assertion, insufficient mutating-call/structured-denial correlation, and pre-try test-auth cleanup gap.
- Source and diff reviewed through GitHub; no independent Windows runtime testing or CI checks. No TASK-012 acceptance, main product merge, or new task.

## M7 round 4 checkpoint (2026-10-09)

- Reviewed executor implementation `0ce55af4` at task branch head `0493fb54`. Previous typing/sandbox-exception/empty-call-ID/pre-try-auth-cleanup blockers improved.
- Round 4 CHANGES_REQUESTED: shell destination matcher can mistake protected path appearing as content or a filename prefix for target write; Codex runtime denial is not demonstrably bound to Guard-blocked tool call.
- Executor reports 360 passed / 2 skipped on Python 3.12.9, live Codex E2E ALLOW/DENY both skipped due to absent dedicated test auth. Static GitHub review only; no CI checks or independent live test.
- M7 UNVERIFIED; do not merge product code or activate another task.

## M7 round 5 checkpoint (2026-10-10)

- Branch implementation/report remote HEAD: `2741178152075a8aaa310ceb02b64e77a598023d`; Executor Report SHA `0876d8c...` is not fetchable from GitHub.
- Round 5 CHANGES_REQUESTED: quoted `>` is mistaken for a redirection, path matching ignores workspace roots, ALLOW completion accepts non-terminal states, and hook stderr is not proof Codex runtime honored the DENY.
- Executor reports Python 3.12.9 362 passed / 2 skipped, 0 failures. Both required isolated online Codex CLI tests still skipped for missing opt-in test credentials; no independent run, CI checks, or real E2E proof.
- M7 remains UNVERIFIED; TASK-012 only active task, no product merge or TASK-013.

## M7 round 6 checkpoint (2026-10-10)

- Reviewed reachable code commit `c7f8bdceb70d6a1eb0a0561a90a10fb080bd89c6` at task report HEAD `4a26d4351063640c44fa435d6f9afa36662b68cf`.
- Static remediation of quoted redirect matching, workspace-bound path comparisons, terminal-success ALLOW and separate runtime DENY evidence appears directionally correct, but **is not real Codex CLI proof**.
- Executor reports 362 passed / 2 skipped (zero failed) on Python 3.12.9; both opt-in online E2E tests SKIPPED due to missing independent test credentials. No independent rerun or CI status.
- Main agent verdict: TASK-012 BLOCKED pending dedicated test-only Codex auth and actual bounded, isolated ALLOW/Completed + DENY/Blocked evidence; no acceptance, merge, or TASK-013. Generic failure status is not proof of hook denial.

## M7 round 7 checkpoint (2026-10-10)

- User obtained dedicated opt-in test authentication and ran the two real Codex CLI E2E pytest tests locally on Windows Python 3.12.9. Both failed before hook execution: exit code 2, `--sandbox workspace-write` incompatible with `--approve-for-me` (2 failed, 7 deselected).
- Main Agent review changes TASK-012 from BLOCKED to CHANGES_REQUESTED; fix both test subprocess argv arrays by removing only `--approve-for-me`, retaining sandbox, isolation and hook trust control, then rerun with dedicated credentials.
- The separate temporary CODEX_HOME PATH alias warning is not presently causal. Real ALLOW/DENY runtime acceptance remains UNVERIFIED; no merge or next task.

## M7 round 8 checkpoint (2026-10-10)

- Live user-run Python 3.12.9 pytest `-k real_codex_cli_pretooluse`: 2 failed / 8 deselected. Previous Codex flag conflict fixed; model and runtime started.
- ALLOW attempted harmless PowerShell file read, rejected by Codex tool router (`CreateProcess ... blocked by policy`) before shell launch despite Codex process returncode 0; no ALLOW runtime verification.
- DENY `deny_proj/.agentcontract/sessions` absent: installed `.codex/hooks.json` is not evidence that hook was called; no Guard BLOCK trace/runtime rejection evidence. File integrity alone is not acceptance.
- Round 8 main-agent verdict: **BLOCKED pending bounded Windows sandbox tool execution + authentic project-hook dispatch preflight**. Investigate explicit test-only `windows.sandbox=elevated`, WindowsApps pwsh restrictions, temp CODEX_HOME helper warning and trust, without changing personal global config or sandbox restrictions.
- No product merge, TASK-012 acceptance, or TASK-013.

## M7 round 9 user-directed product guarantee (2026-10-10)

- Existing Windows account, Python and Codex are mandatory baseline; no VM/dedicated account/admin shell or interruption to other active sessions as prerequisites.
- AgentContract-owned integration, default tests and uninstall may mutate only named project; no global Codex auth/config/trust/plugins, profile ACLs, global shared runtimes or other processes.
- Windows elevated sandbox ACL changes despite isolated CODEX_HOME: no automatic provisioning, no unsafe mode fallback. Explicitly report upstream environment blocked.
- Offline no-login safe doctor/smoke is required; actual Codex online ALLOW/DENY is separate optional QA and currently UNVERIFIED.
- Round 9 CHANGES_REQUESTED for minimal safe UX and regression hardening. No main product merge or TASK-013.

## M7 round 10 checkpoint (2026-10-10)

- Reviewed reachable implementation `1df5f26325d968e0111fb1f9cf7b2263b544a0b3`, branch report `8bc5b3700391c9f987195000f125e8e3d2d7414b`; offline executor Windows Python 3.12.9 373 passed / 2 skipped; no CI or independent runtime evidence.
- New project-local offline `agentcontract codex doctor` improves UX, but its direct in-process `run_hook` cannot establish actual project hook command dispatch or Codex acceptance. Doctor may PASS if hook command contains marker but is not executable, and overclaims integrity without evidence.
- Live E2E helper erroneously treats a known nonfatal temp CODEX_HOME PATH-alias warning as fatal upstream block and may skip genuine tests. Must separate warnings from actual tool/sandbox failures.
- Round 10 CHANGES_REQUESTED; enforce truthful status/cleanup and simple safe offline test, no unsafe sandbox setup, no main product merge/TASK-013; real Codex E2E still UNVERIFIED.

## M7 round 11 checkpoint (2026-10-10)

- Reviewed implementation `75abc98a8838869cc4038c168bded3cce3342134`, report head `cf9507189715358f22329cf8fffad92f404b8235`. Executor reports Windows Python 3.12.9 377 passed/2 skipped; both true online Codex E2E still skipped/UNVERIFIED.
- Nonfatal PATH warning no longer treated as blocker, doctor now calls actual configured SessionStart/PreToolUse via safe offline subprocess, and cleanup errors are visible.
- Round 11 CHANGES_REQUESTED: doctor currently accepts garbage or structured nonempty ALLOW stdout, contradicting required empty-wire-format; global Codex home snapshot observes only additions + three files and may falsely claim entire home unchanged after deletion or other changes.
- Fix two narrow evidence issues, maintain normal Windows existing Codex account/project isolation; no product merge/TASK-013.

## M7 round 12 checkpoint (2026-10-10)

- Verified executor received Round 11 instructions via task branch at `8c27d769` and reviewed code commit `9b3538f4` plus latest Executor Report. Reported offline full suite 383 passed, 2 skipped; not independently rerun.
- Offline Doctor registered-hook subprocess wire format now rejects junk/structured ALLOW stdout; global Codex home snapshot detects top-level additions/deletions and tracked file edits/read errors, and truthfully limits inspection scope.
- Main-agent offline code review PASS; product task overall **BLOCKED** because real Codex CLI ALLOW/Completed + DENY/Blocked with linked Guard traces has not been established; Windows native Codex tool policy and CUA ACL refresh upstream failures remain. No main product merge/TASK-013.
- User may run offline local pytest and temporary project install/doctor/status/audit/uninstall without invoking native sandbox/elevated Windows setup. Do not modify global Codex config/auth/ACL/processes.

## M7 round 12 user-run offline validation (2026-10-10)

- User verified local task branch HEAD `ab13061` via safe fast-forward. Windows offline pytest excluding both real online Codex cases: **383 passed, 2 deselected in 29.46 seconds**.
- Disposable TEMP project: 5 project-only hook events installed; `agentcontract codex doctor` exited 0, verifying child-process SessionStart/PreToolUse, SpecGuard ALLOW/BLOCK trace and correct stdout JSON/wire format, cleanup and scoped tracked global Codex home integrity. Status saw zero persisted sessions; uninstall removed project hooks file (Test-Path False). Parent PYTHONPATH restored.
- This establishes OFFLINE_VALIDATED from user-run logs. Genuine native Codex CLI runtime ALLOW/Completed + DENY/Blocked E2E still UNVERIFIED; TASK-012 overall BLOCKED. No product merge/TASK-013, and no global ACL/config/process modifications or sandbox bypass.

