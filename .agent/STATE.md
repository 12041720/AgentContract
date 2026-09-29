# Persistent Project State

> This file is authoritative. Read it before doing any work.

## Project

- Name: AgentContract
- Mission: Runtime constraint tracking and evidence-grounded completion verification for long-horizon tool-using agents.
- Stage: Measurable Reliability
- Architecture version: 0.1
- Default branch: `main`

## Current active task

- Task: **TASK-008 — External integration adapters and OpenTelemetry bridge**
- Task file: `.agent/tasks/TASK-008.md`
- Work branch: `task/TASK-008-integrations`
- Status: **CHANGES_REQUESTED**
- Owner: Execution agent
- Main-agent review: TASK-008 narrow integration fixes requested after review of `8a11a0c079926c2f98a1f01df380aef2b8484429`

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
- TASK-008 first implementation reviewed; OTLP wire IDs and external path typing need narrow fixes.

## Current design decisions

1. Core logic is developed against the user's installed local Python **3.12.9** and remains vendor-neutral. Do not install alternate Python interpreters solely for compatibility testing.
2. Pydantic models are used at system boundaries and for durable domain state.
3. Constraint tracking and evidence verification are separate subsystems connected through shared provenance/trace identifiers.
4. Hard constraints must be enforceable without asking the same LLM that generated the action to self-police.
5. Verification has explicit states; unknown/unverified is distinct from false.
6. MVP targets coding/tool agents first but domain types must not hard-code Git or filesystem semantics.
7. Main-agent coordination is persisted under `.agent/`; chat history is not a source of truth.

## Review gate

The main agent will not activate TASK-009 until TASK-008 satisfies its acceptance criteria and is reviewed.

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
