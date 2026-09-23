# Persistent Project State

> This file is authoritative. Read it before doing any work.

## Project

- Name: AgentContract
- Mission: Runtime constraint tracking and evidence-grounded completion verification for long-horizon tool-using agents.
- Stage: Foundation
- Architecture version: 0.1
- Default branch: `main`

## Current active task

- Task: **TASK-001 — Core domain model and Constraint Ledger**
- Task file: `.agent/tasks/TASK-001.md`
- Work branch: `task/TASK-001-core-ledger`
- Status: **CHANGES_REQUESTED**
- Owner: Execution agent
- Main-agent review: TASK-001 second-round changes requested after review of `85f0195326a5dbba7f51ddf4863e0ba550affe28`

## Main-agent checkpoint

- Repository initialized on 2026-09-22.
- Persistent main-agent/executor protocol established.
- High-level architecture fixed for v0.1.
- TASK-001 round-2 implementation was reviewed. Python 3.11 compatibility improved, but immutable metadata and lifecycle transition enforcement still have blockers. No implementation task has been accepted yet.

## Current design decisions

1. Core logic is Python 3.11+ and vendor-neutral.
2. Pydantic models are used at system boundaries and for durable domain state.
3. Constraint tracking and evidence verification are separate subsystems connected through shared provenance/trace identifiers.
4. Hard constraints must be enforceable without asking the same LLM that generated the action to self-police.
5. Verification has explicit states; unknown/unverified is distinct from false.
6. MVP targets coding/tool agents first but domain types must not hard-code Git or filesystem semantics.
7. Main-agent coordination is persisted under `.agent/`; chat history is not a source of truth.

## Review gate

The main agent will not activate TASK-002 until TASK-001 fixes the recorded blockers, passes Python 3.11+ checks, and is re-reviewed.

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
