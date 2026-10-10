# Task Roadmap

Status values: `PLANNED`, `READY_FOR_EXECUTOR`, `IN_PROGRESS`, `READY_FOR_REVIEW`, `ACCEPTED`, `CHANGES_REQUESTED`, `BLOCKED`.

| Task | Title | Status | Depends on |
|---|---|---|---|
| TASK-001 | Core domain model and Constraint Ledger | ACCEPTED | — |
| TASK-002 | Unified trace and provenance model | ACCEPTED | TASK-001 |
| TASK-003 | SpecGuard pre/post action validation engine | ACCEPTED | TASK-001, TASK-002 |
| TASK-004 | Claims, evidence graph, and deterministic EvidenceGate | ACCEPTED | TASK-002 |
| TASK-005 | Agent/tool runtime wrapper and end-to-end demo | ACCEPTED | TASK-003, TASK-004 |
| TASK-006 | LLM-assisted requirement/claim extraction adapters | ACCEPTED | TASK-001, TASK-004 |
| TASK-007 | Benchmark scenarios and reliability metrics | ACCEPTED | TASK-005, TASK-006 |
| TASK-008 | OpenTelemetry + external agent adapters | ACCEPTED | TASK-005 |
| TASK-009 | Integration hardening, CLI/API packaging, and documentation | ACCEPTED | TASK-007, TASK-008 |

## Milestones

### M1 — Executable contract core
TASK-001 through TASK-004.

Goal: constraints can be stored/evolved, actions can be evaluated, claims can be checked against structured evidence without depending on a specific model.

### M2 — Working AgentContract demo
TASK-005 through TASK-006.

Goal: a small coding/tool agent can be wrapped by AgentContract and visibly blocked/verified.

### M3 — Measurable reliability
TASK-007.

Goal: compare baseline agent vs AgentContract using constraint violation rate, unsupported completion rate, false blocking, task success, and overhead.

### M4 — Integration-ready project
TASK-008 through TASK-009.

Goal: adapters, OTel-compatible tracing, CLI/API, polished README, reproducible examples.

## Backlog / research candidates

These are deliberately not active yet:
- constraint graph conflict-resolution policies;
- probabilistic evidence strength;
- LLM-judge fallback for semantic constraints;
- Claude Code hooks adapter;
- Codex rollout-trace adapter;
- MCP middleware adapter;
- multi-agent shared contract;
- long-context constraint retention benchmark.

The main agent promotes backlog items only when the core is stable.

### M4 — v0.1 Completion

Status: **COMPLETE**

TASK-001 through TASK-009 are accepted. No next task is activated automatically.

## M5 — Real Agent Harness Integration

| Task | Title | Status | Depends on |
|---|---|---|---|
| TASK-010 | Real Codex Harness Integration via Lifecycle Hooks | ACCEPTED | TASK-009 |

Goal: prove AgentContract against a real autonomous coding-agent tool loop rather than canned demo actions.

M5 status: **COMPLETE**. TASK-010 accepted on 2026-10-09; no next task activated automatically.

## M6 — Codex Integration Isolation & Operational Safety

| Task | Title | Status | Depends on |
|---|---|---|---|
| TASK-011 | Codex Configuration Isolation & Zero External Side Effects | ACCEPTED | TASK-010 |

Goal: AgentContract tests and project hooks must never change or activate in unrelated Codex desktop/CLI workspaces or mutate the normal user's global Codex home.

M6 status: **COMPLETE** — TASK-011 accepted on 2026-10-09, selectively integrated into `main` as `a8343521416cbe97a257a4c06f19730c3265ee60`. No next task activated. Codex Desktop smoke checklist remains MANUAL/UNVERIFIED.

## M7 — Codex PreToolUse Runtime Compatibility

| Task | Title | Status | Depends on |
|---|---|---|---|
| TASK-012 | Codex CLI PreToolUse Output Protocol Compatibility | CHANGES_REQUESTED | TASK-011 |

Goal: correct ALLOW wire format while demonstrating real runtime ALLOW/Completed and DENY/Blocked under truly isolated, sandboxed Codex tests.

M7 status: **BLOCKED / LIVE E2E UNVERIFIED** — round 6 review (2026-10-10). Static remediation reviewed; executor reports 362 passed / 2 skipped. Both real Codex CLI ALLOW/DENY tests intentionally SKIPPED because no independent test-only auth was supplied. Await bounded isolated live E2E evidence, not another offline-only implementation iteration. Details in `.agent/tasks/TASK-012.md`. No product merge or TASK-013.

M7 round 7 update (2026-10-10): dedicated test auth now available. Real E2E invocation attempted, but both tests fail at Codex CLI argument parsing (workspace-write sandbox conflicts with `--approve-for-me`), before AgentContract hook execution. Status **CHANGES_REQUESTED** for minimal argv correction plus live rerun; M7 still UNVERIFIED. See TASK-012 review; no product merge or TASK-013.

M7 round 8 update (2026-10-10): **BLOCKED / LIVE E2E FAILED PRECONDITIONS**. Authenticated real CLI run selected ALLOW/DENY tests; 2 failed. Harmless read denied by Windows Codex tool policy before child process; DENY project session/Guard trace absent. Need bounded Windows sandbox native-tool preflight and verified project hook activation, not a security bypass. Details in task review. No merge/TASK-013.

M7 round 9 (2026-10-10): CHANGES_REQUESTED — improve normal Windows/Codex ease of use and avoid ALL AgentContract-caused global ACL/config/auth/process interference. No VM/dedicated OS identity/closing other Codex sessions, no elevated native sandbox automatic setup; add default offline safe smoke and explicit upstream BLOCKED/UNVERIFIED diagnostics. Real live E2E still unverified. See TASK-012 and AGENTS.md.

M7 round 10 review (2026-10-10): CHANGES_REQUESTED. Offline doctor and safe upstream block classification introduced, executor reports 373 passed/2 skipped, but nonfatal PATH alias warning triggers false E2E skip, doctor direct run_hook can falsely pass invalid installed handler and overstates global integrity. Fix evidence/diagnostics; real Codex CLI remains UNVERIFIED. See TASK-012. No merge/TASK-013.

M7 round 11 review (2026-10-10): CHANGES_REQUESTED — executor reports 377 passed / 2 skipped; doctor improves command verification and warning classification. Remaining blockers: doctor incorrectly accepts nonempty ALLOW stdout, and global home snapshot/unchanged claim misses deletions/other files. Need precise wire-format regression + honest bounded global integrity checking. Live real Codex E2E UNVERIFIED, no merge/TASK-013. See TASK-012 review.

M7 round 12 (2026-10-10): Offline doctor and scoped integrity/code changes PASS static main-agent review, executor reports 383 passed/2 skipped; TASK-012 overall BLOCKED pending genuine Codex Windows native runtime ALLOW/Completed + DENY/Blocked E2E. Safe temporary-project offline local validation permitted; no global Codex mutation, main product merge or TASK-013. See TASK-012 Round 12.

M7 round 13 (2026-10-10): Real user opt-in Windows Codex 0.162.0 E2E: 2 skipped, 13 deselected, 1 warning; both ALLOW read and DENY write blocked by Codex native CreateProcess policy on WindowsApps/MSIX pwsh.exe before actual tool spawn. Hook invocation/enforcement UNVERIFIED. Separate test bug: Python subprocess default GBK decoding failed on UTF-8 Codex output; fix E2E UTF-8 decode and add diagnostics/regression. Keep 383-pass offline gate and external environment BLOCKED, do not merge/start TASK-013.

M7 round 14 (2026-10-10): CHANGES_REQUESTED narrowly for evidence accuracy. UTF-8 process decode fix landed (agent reports 387 passed/2 skipped), but three-way diagnostics may falsely claim Codex runtime enforcement via "Completed"/"Blocked" prose and PreToolUse hook invocation from unrelated lifecycle trace events. Root-cause WindowsApps/MSIX claims require evidence or uncertainty labels. Native live E2E still BLOCKED/UNVERIFIED, no main merge/TASK-013. See Round 14 TASK-012.

M7 round 15 (2026-10-10): CHANGES_REQUESTED for single diagnostic false-positive: `format_e2e_diagnostics` reports ENFORCED from unrelated tool machine event and Guard verdict, without same-call identity; `agent_message` can count as completed tool. Require genuine per-call/tool evidence or conservative UNVERIFIED, negative tests. Executor reports 391 passed/2 skipped; native Codex real E2E still UPSTREAM_ENV_BLOCKED, no rerun/merge/TASK-013. See task Round 15.

