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
- Main-agent review: Round 6 BLOCKED (static remediation reviewed; two required live Codex CLI tests skipped for missing independent test credentials)
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
