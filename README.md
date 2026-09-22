# AgentContract

**Runtime Constraint Tracking and Evidence-Grounded Verification for Long-Horizon Agents**

AgentContract is a reliability layer for tool-using agents. It turns user requirements into a persistent execution contract, checks agent actions against that contract, and verifies completion claims against observable evidence.

## Core idea

```text
User intent
    ↓
Requirement / constraint extraction
    ↓
Constraint Ledger
    ↓
Agent actions ──→ SpecGuard
    ↓
Tool results / workspace state
    ↓
Evidence Graph
    ↓
EvidenceGate
    ↓
Verified completion
```

The project focuses on two failure modes:

1. **Constraint drift** — a long-running agent forgets, overrides, or violates user requirements.
2. **Unsupported completion** — an agent claims something was completed or verified without sufficient execution evidence.

## Planned components

- **Constraint Ledger** — versioned constraints, scope, source, priority, revocation, supersession, and conflicts.
- **SpecGuard** — pre-action, post-action, and finalization checks.
- **Trace Store** — normalized agent/tool events and provenance.
- **Evidence Graph** — links claims to supporting or contradicting evidence.
- **EvidenceGate** — completion-readiness and claim verification.
- **Adapters** — wrappers/hooks for coding and tool-using agents.
- **Benchmark** — measures constraint violations, unsupported completion claims, false blocking, overhead, and task success.

## Development workflow

This repository uses a persistent main-agent / execution-agent workflow.

- Main-agent state and task instructions live under [`.agent/`](.agent/).
- Every execution agent must read [`AGENTS.md`](AGENTS.md) and the active task file before changing code.
- Execution agents implement only the assigned task and record their handoff in the task file.
- The main agent reviews code and tests, records the verdict, then updates the next task.

Start with [`.agent/STATE.md`](.agent/STATE.md).
