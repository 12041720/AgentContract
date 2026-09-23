# TASK-001 — Core domain model and Constraint Ledger

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-001-core-ledger`  
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
- Implemented core constraint domain models in `src/agentcontract/constraints/models.py`:
  - `Constraint`, `ConstraintProvenance`, `ConstraintScope`, `ConstraintRelation`.
  - Typed `StrEnum` definitions: `ConstraintSource` (USER, POLICY, REPOSITORY, TOOL, AGENT_INFERENCE), `ConstraintStrength` (HARD, SOFT, ASSUMPTION), `ConstraintStatus` (ACTIVE, REVOKED, SUPERSEDED, CONFLICTED).
  - Enforced Invariant 8 via model validation: an `AGENT_INFERENCE` cannot be declared with `HARD` strength, guaranteeing assumptions remain distinguishable from user authority.
  - Frozen Pydantic models preventing accidental mutation and ensuring immutable value semantics.
- Implemented typed domain exceptions in `src/agentcontract/constraints/exceptions.py`:
  - `ConstraintError`, `ConstraintNotFoundError`, `DuplicateConstraintError`, `InvalidConstraintTransitionError`, `ConstraintValidationError`.
- Implemented in-memory, version-preserving `ConstraintLedger` and `LedgerSnapshot` in `src/agentcontract/constraints/ledger.py`:
  - `add`: registers active constraints with duplicate ID checks.
  - `get`: retrieves any constraint by ID across all lifecycle statuses.
  - `list_active`: returns only active constraints, excluding revoked/superseded entries.
  - `list_all`: returns full constraint history.
  - `revoke`: marks active constraints as revoked with reason and timestamp while preserving provenance and scope. Explicitly rejects transitions on terminal constraints.
  - `supersede`: marks an active constraint as superseded, activates replacement, links forward/backward lineage (`supersedes` / `superseded_by`), and preserves original records and provenance. Rejects transitions on terminal constraints, duplicate IDs, or identical IDs.
  - `mark_conflicted`: tracks conflicting constraints and updates status to `CONFLICTED`.
  - `get_history`: computes full ordered supersession lineage from root to latest replacement.
  - `snapshot`, `to_dict`, `to_json`, `from_snapshot`, `from_dict`, `from_json`: robust JSON/dict serialization round-trips preserving all fields, IDs, statuses, relations, scopes, and provenances.
- Exported public constraint API in `src/agentcontract/constraints/__init__.py` and root package `src/agentcontract/__init__.py`.
- Configured pytest `pythonpath = ["src"]` in `pyproject.toml`.
- Implemented comprehensive unit tests covering all 8 recommended scenarios plus edge cases (22 tests total).

**Files changed:**  
- `src/agentcontract/constraints/models.py` (new)
- `src/agentcontract/constraints/ledger.py` (new)
- `src/agentcontract/constraints/exceptions.py` (new)
- `src/agentcontract/constraints/__init__.py` (updated)
- `src/agentcontract/__init__.py` (updated)
- `pyproject.toml` (updated with pythonpath)
- `tests/__init__.py` (new)
- `tests/constraints/__init__.py` (new)
- `tests/constraints/test_models.py` (new)
- `tests/constraints/test_ledger.py` (new)
- `.agent/tasks/TASK-001.md` (updated Executor Report)

**Tests/checks:**  
- `python -m pytest -v`: 22 passed in 0.39s (100% pass rate).
- Validated Python 3.12.9 environment compatibility.
- Scenarios tested:
  1. Add explicit hard user constraint ("do not modify DB schema").
  2. Add agent assumption and demonstrate it remains distinguishable from user authority.
  3. Revoke active constraint, check list_active vs get, verify provenance/scope preservation.
  4. Supersede "must use Redis" with "PostgreSQL allowed", verify old record remains queryable and history links both.
  5. Attempt to revoke/supersede already terminal (revoked or superseded) constraints and assert explicit `InvalidConstraintTransitionError`.
  6. Duplicate ID rejection on add and supersede.
  7. Serialization round-trip (`to_json` -> `from_json`, `to_dict` -> `from_dict`) verifying semantic state equality.
  8. Active listing excludes revoked and superseded entries.
  9. Multi-hop supersession lineage traversal (A -> B -> C).
  10. Conflict tracking and validation.
  11. Empty ID/name validation and model immutability.
  12. Top-level package export checks.

**Known limitations:**  
- In-memory only for v0.1 (as specified by TASK-001 scope; persistent storage like SQLite/PostgreSQL is deferred to later milestones).
- SpecGuard rules and NL constraint extraction are not included (out of scope per task specification).

**Commit/PR:**  
- Branch: `task/TASK-001-core-ledger`
- Commit SHA: `0ce2fd8`

**Questions/blockers:**  
- None. All acceptance criteria and suggested test cases for TASK-001 are met and verified.

## Main Agent Review

> Main agent only.

**Verdict:** PENDING

**Findings:**  
Pending implementation.

**Next instruction:**  
Do not start TASK-002 until this section says ACCEPTED.
