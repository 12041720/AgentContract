# Persistent Project State

> This file is authoritative. Read it before doing any work.

## Project

- Name: AgentContract
- Mission: Runtime constraint tracking and evidence-grounded completion verification for long-horizon tool-using agents.
- Stage: Foundation
- Architecture version: 0.1
- Default branch: `main`

## Current active task

- Task: **TASK-003 — SpecGuard pre/post action validation engine**
- Task file: `.agent/tasks/TASK-003.md`
- Work branch: `task/TASK-003-specguard`
- Status: **CHANGES_REQUESTED**
- Owner: Execution agent
- Main-agent review: TASK-003 second-round changes requested after review of `9146c0e98e5446762c635252f0bf064e7eea62e9`

## Main-agent checkpoint

- Repository initialized on 2026-09-22.
- Persistent main-agent/executor protocol established.
- High-level architecture fixed for v0.1.
- TASK-001 accepted after final hardening and integrated to `main` as `48a7ae1cc07025a400b11804c298c2970cfc5107`.
- TASK-002 accepted and integrated to `main` as `2c71b2509dc82a95a2c3ce298602811f549ac1ff`.
- TASK-003 round-2 implementation fixed the first review blockers; two narrow semantic gaps remain in exact selector equality and REQUIRE/PREFER model validation.

## Current design decisions

1. Core logic is developed against the user's installed local Python **3.12.9** and remains vendor-neutral. Do not install alternate Python interpreters solely for compatibility testing.
2. Pydantic models are used at system boundaries and for durable domain state.
3. Constraint tracking and evidence verification are separate subsystems connected through shared provenance/trace identifiers.
4. Hard constraints must be enforceable without asking the same LLM that generated the action to self-police.
5. Verification has explicit states; unknown/unverified is distinct from false.
6. MVP targets coding/tool agents first but domain types must not hard-code Git or filesystem semantics.
7. Main-agent coordination is persisted under `.agent/`; chat history is not a source of truth.

## Review gate

The main agent will not activate TASK-004 until TASK-003 satisfies its acceptance criteria and is reviewed.

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
