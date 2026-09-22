# TASK-001 — Core domain model and Constraint Ledger

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Main-agent review:** pending

## Objective

Implement the first stable domain layer for AgentContract: constraint/provenance models and an in-memory, version-preserving `ConstraintLedger`.

This task intentionally does **not** use an LLM. It establishes deterministic state semantics that later SpecGuard and extraction adapters can rely on.

## Required reading

Before implementation:
1. `AGENTS.md`
2. `.agent/STATE.md`
3. `docs/ARCHITECTURE.md`
4. this file

## Scope

Implement under `src/agentcontract/constraints/` plus tests.

### Required domain concepts

At minimum define typed/serializable models for:

- `Constraint`
- `ConstraintId` or equivalent stable identifier
- source/provenance
- strength/authority
- lifecycle status
- scope
- relation/history metadata sufficient for supersession/revocation

Recommended enums (names may vary if justified):
- source: `USER`, `POLICY`, `REPOSITORY`, `TOOL`, `AGENT_INFERENCE`
- strength: `HARD`, `SOFT`, `ASSUMPTION`
- status: `ACTIVE`, `REVOKED`, `SUPERSEDED`, `CONFLICTED`

Do not hard-code the model exclusively to filesystem constraints. A scope may contain generic structured selectors/metadata even if initial tests use coding examples.

### ConstraintLedger behavior

Provide an in-memory ledger with explicit operations equivalent to:

- add a constraint;
- get by ID;
- list active constraints;
- revoke a constraint;
- supersede an existing constraint with a replacement;
- preserve immutable/historical provenance after lifecycle transitions;
- serialize/deserialize ledger state.

Exact method names are up to the executor, but semantics must be obvious and documented.

### Lifecycle invariants

The implementation must enforce these rules:

1. IDs are stable and unique.
2. A revoked constraint is no longer active.
3. A superseded constraint is no longer active.
4. Superseding creates/links a replacement and preserves the old record.
5. Invalid transitions fail explicitly rather than silently succeeding.
6. Source and provenance are never discarded during transitions.
7. Serialization round-trip preserves IDs, statuses, relations, scope, and provenance.
8. An `AGENT_INFERENCE`/assumption cannot be represented indistinguishably from an explicit user hard constraint.

## Out of scope

Do **not** implement in TASK-001:
- natural-language requirement extraction;
- LLM calls;
- SpecGuard action evaluation;
- evidence/claim verification;
- database persistence;
- OpenTelemetry;
- FastAPI/CLI;
- MCP/Codex/Claude adapters.

Avoid speculative abstractions for these future modules.

## Expected files

The exact split may vary, but the main agent expects something close to:

```text
src/agentcontract/constraints/
├── __init__.py
├── models.py
└── ledger.py

tests/
└── constraints/
    ├── test_models.py
    └── test_ledger.py
```

## Acceptance criteria

Main-agent review will require all of the following:

- [ ] package imports successfully on Python 3.11+;
- [ ] Pydantic is used for durable domain models;
- [ ] enums/types prevent magic-string lifecycle state in core logic;
- [ ] ledger operations above are implemented;
- [ ] invalid lifecycle transitions have typed/clear exceptions;
- [ ] history/provenance survives revoke/supersede;
- [ ] JSON/model serialization round-trip tests pass;
- [ ] tests cover happy path and failure paths;
- [ ] no LLM/API/network dependency in the core;
- [ ] public constraint API has concise docstrings/type hints;
- [ ] `pytest` passes.

## Suggested test cases

At minimum include scenarios equivalent to:

1. Add explicit hard user constraint: “do not modify DB schema”.
2. Add agent assumption and demonstrate it remains distinguishable from user authority.
3. Revoke an active constraint.
4. Supersede “must use Redis” with “PostgreSQL allowed”; old record remains queryable.
5. Attempt to revoke/supersede an already terminal constraint and assert explicit failure.
6. Duplicate ID rejection.
7. Serialize ledger → reconstruct → compare semantic state.
8. Active listing excludes revoked/superseded entries.

## Design freedom

The executor may introduce a small amount of extra structure when it materially improves correctness. Keep it simple. The main agent prefers a coherent narrow implementation over a generic rule engine.

If a requirement is ambiguous, record the ambiguity in **Executor Report** rather than silently widening scope.

## Required checks

Run at least:

```bash
python -m pytest
```

If lint/type tooling is added by the executor, also report its results.

## Executor Report

> Execution agent: fill this section only after implementation.

**Implementation summary:**  
TBD

**Files changed:**  
TBD

**Tests/checks:**  
TBD

**Known limitations:**  
TBD

**Commit/PR:**  
TBD

**Questions/blockers:**  
TBD

## Main Agent Review

> Main agent only.

**Verdict:** PENDING

**Findings:**  
Pending implementation.

**Next instruction:**  
Do not start TASK-002 until this section says ACCEPTED.
