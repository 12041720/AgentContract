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
| TASK-012 | Codex CLI PreToolUse Output Protocol Compatibility | BLOCKED | TASK-011 |

Goal: correct ALLOW wire format while demonstrating real runtime ALLOW/Completed and DENY/Blocked under truly isolated, sandboxed Codex tests.

M7 status: **BLOCKED / LIVE E2E UNVERIFIED** — round 6 review (2026-10-10). Static remediation reviewed; executor reports 362 passed / 2 skipped. Both real Codex CLI ALLOW/DENY tests intentionally SKIPPED because no independent test-only auth was supplied. Await bounded isolated live E2E evidence, not another offline-only implementation iteration. Details in `.agent/tasks/TASK-012.md`. No product merge or TASK-013.
