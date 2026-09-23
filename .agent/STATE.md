# Persistent Project State

> This file is authoritative. Read it before doing any work.

## Project

- Name: AgentContract
- Mission: Runtime constraint tracking and evidence-grounded completion verification for long-horizon tool-using agents.
- Stage: Foundation
- Architecture version: 0.1
- Default branch: `main`

## Current active task

- Task: **TASK-002 — Unified trace and provenance model**
- Task file: `.agent/tasks/TASK-002.md`
- Work branch: `task/TASK-002-trace-model`
- Status: **CHANGES_REQUESTED**
- Owner: Execution agent
- Main-agent review: TASK-002 changes requested after review of `431534bd21ab62751a63b47db19d6368c5828a08`

## Main-agent checkpoint

- Repository initialized on 2026-09-22.
- Persistent main-agent/executor protocol established.
- High-level architecture fixed for v0.1.
- TASK-001 accepted after final hardening and integrated to `main` as `48a7ae1cc07025a400b11804c298c2970cfc5107`.
- TASK-002 first implementation was reviewed; two trace-integrity blockers remain around ToolResult provenance and durable output immutability.

## Current design decisions

1. Core logic is developed against the user's installed local Python **3.12.9** and remains vendor-neutral. Do not install alternate Python interpreters solely for compatibility testing.
2. Pydantic models are used at system boundaries and for durable domain state.
3. Constraint tracking and evidence verification are separate subsystems connected through shared provenance/trace identifiers.
4. Hard constraints must be enforceable without asking the same LLM that generated the action to self-police.
5. Verification has explicit states; unknown/unverified is distinct from false.
6. MVP targets coding/tool agents first but domain types must not hard-code Git or filesystem semantics.
7. Main-agent coordination is persisted under `.agent/`; chat history is not a source of truth.

## Review gate

The main agent will not activate TASK-003 until TASK-002 satisfies its acceptance criteria and is reviewed.

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
