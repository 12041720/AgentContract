# Task Roadmap

Status values: `PLANNED`, `READY_FOR_EXECUTOR`, `IN_PROGRESS`, `READY_FOR_REVIEW`, `ACCEPTED`, `CHANGES_REQUESTED`, `BLOCKED`.

| Task | Title | Status | Depends on |
|---|---|---|---|
| TASK-001 | Core domain model and Constraint Ledger | ACCEPTED | — |
| TASK-002 | Unified trace and provenance model | CHANGES_REQUESTED | TASK-001 |
| TASK-003 | SpecGuard pre/post action validation engine | PLANNED | TASK-001, TASK-002 |
| TASK-004 | Claims, evidence graph, and deterministic EvidenceGate | PLANNED | TASK-002 |
| TASK-005 | Agent/tool runtime wrapper and end-to-end demo | PLANNED | TASK-003, TASK-004 |
| TASK-006 | LLM-assisted requirement/claim extraction adapters | PLANNED | TASK-001, TASK-004 |
| TASK-007 | Benchmark scenarios and reliability metrics | PLANNED | TASK-005, TASK-006 |
| TASK-008 | OpenTelemetry + external agent adapters | PLANNED | TASK-005 |
| TASK-009 | CLI/API packaging and documentation | PLANNED | TASK-007 |

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
