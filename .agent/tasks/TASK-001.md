# TASK-001 — Core domain model and Constraint Ledger

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-001-core-ledger`  
**Main-agent review:** changes requested

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
- **Initial Implementation (Iteration 1, `0ce2fd8`):**
  - Core domain models: `Constraint`, `ConstraintProvenance`, `ConstraintScope`, `ConstraintRelation`.
  - Enums: `ConstraintSource`, `ConstraintStrength`, `ConstraintStatus`.
  - Invariant 8 enforcement: `AGENT_INFERENCE` prohibited from `HARD` strength.
  - In-memory version-preserving `ConstraintLedger` with `add`, `get`, `list_active`, `list_all`, `revoke`, `supersede`, `mark_conflicted`, `get_history`, `snapshot`, `to_json`/`from_json`, `to_dict`/`from_dict`.
- **Review Fixes & Hardening (Iteration 2, `85f0195`):**
  - **Fixed Blocker 1 (Python 3.11 Compatibility):** Replaced PEP 695 `type ConstraintId = str` with `ConstraintId: TypeAlias = str` (`from typing import TypeAlias`). Verified full test suite runs cleanly on both Python 3.11.12 and Python 3.12.9.
  - **Fixed Blocker 2 (Deep Immutability & Defensive Isolation):**
    - Implemented `FrozenDict(dict[str, Any])` with custom Pydantic core schema (`__get_pydantic_core_schema__`) and recursive deep-freezing (`_freeze_value`) for nested dictionaries, lists, and sets.
    - Replaced mutable lists with immutable tuples for sequence fields: `ConstraintScope.paths`, `ConstraintScope.tools`, `ConstraintScope.actions`, `ConstraintRelation.conflicts_with`, and `LedgerSnapshot.constraints`.
    - Typed metadata and selectors fields as `FrozenDict`: `ConstraintProvenance.metadata`, `ConstraintScope.selectors`, `ConstraintRelation.metadata`, and `LedgerSnapshot.metadata`.
    - Added extensive regression tests ensuring that in-place mutation of collections, dict items, or external input references cannot alter stored ledger/snapshot state.
  - **Fixed Required Hardening (Explicit Lifecycle State Machine):**
    - Defined explicit transition table `ALLOWED_TRANSITIONS` in `models.py`.
    - `ledger.add`: Enforced that new constraints must enter as `ACTIVE`; rejected pre-set `REVOKED`, `SUPERSEDED`, or `CONFLICTED` constraints with `InvalidConstraintTransitionError`.
    - `ledger.supersede`: Enforced that replacement constraints must enter as `ACTIVE`; rejected non-active replacements.
    - Formalized and implemented `CONFLICTED` transition rules:
      - `CONFLICTED -> REVOKED` is legal (resolves conflict by cancelling one of the conflicting requirements).
      - `CONFLICTED -> SUPERSEDED` is legal (resolves conflict by superseding with a harmonized requirement).
      - `CONFLICTED -> ACTIVE` is legal via new `ledger.resolve_conflict(constraint_id, reason=...)`.
    - Disallowed marking conflict on or with terminal (`REVOKED`/`SUPERSEDED`) constraints.
    - Re-confirmed terminal states (`REVOKED`, `SUPERSEDED`) strictly reject all further transitions.

**Files changed:**  
- `src/agentcontract/constraints/models.py` (updated: `TypeAlias`, `FrozenDict`, `_freeze_value`, `ALLOWED_TRANSITIONS`, tuple/FrozenDict fields)
- `src/agentcontract/constraints/ledger.py` (updated: lifecycle checks in `add`/`revoke`/`supersede`/`mark_conflicted`, added `resolve_conflict`, immutable `LedgerSnapshot`)
- `src/agentcontract/constraints/exceptions.py` (typed exceptions)
- `src/agentcontract/constraints/__init__.py` (exported `FrozenDict`, `ALLOWED_TRANSITIONS`, and core domain types)
- `src/agentcontract/__init__.py` (root package exports)
- `pyproject.toml` (pytest `pythonpath = ["src"]`)
- `tests/constraints/test_models.py` (updated: added deep immutability and external reference isolation tests)
- `tests/constraints/test_ledger.py` (updated: added lifecycle transition tests for CONFLICTED/active/terminal states, snapshot immutability)
- `.agent/tasks/TASK-001.md` (updated Executor Report)

**Tests/checks:**  
- **Python 3.11.12 Check:**
  - Command: `uv run --python 3.11 --with pytest python -m pytest -v`
  - Result: 26 passed in 0.34s (100% pass rate).
- **Python 3.12.9 Check:**
  - Command: `python -m pytest -v`
  - Result: 26 passed in 0.48s (100% pass rate).
- **Scenarios & Hardening Tested (26 tests total):**
  1. Add explicit hard user constraint ("do not modify DB schema").
  2. Add agent assumption and demonstrate it remains distinguishable from user authority.
  3. Revoke active constraint, check list_active vs get, verify provenance/scope preservation.
  4. Supersede "must use Redis" with "PostgreSQL allowed", verify old record remains queryable and history links both.
  5. Attempt to revoke/supersede already terminal (revoked or superseded) constraints and assert explicit `InvalidConstraintTransitionError`.
  6. Duplicate ID rejection on add and supersede.
  7. Serialization round-trip (`to_json` -> `from_json`, `to_dict` -> `from_dict`) verifying semantic state equality.
  8. Active listing excludes revoked and superseded entries.
  9. Multi-hop supersession lineage traversal (A -> B -> C).
  10. Not found error handling for lookup, revoke, supersede, and history.
  11. `add` rejects non-active initial states (rejects REVOKED, SUPERSEDED, CONFLICTED).
  12. `supersede` rejects non-active replacement states (rejects REVOKED, SUPERSEDED, CONFLICTED replacements).
  13. `CONFLICTED` lifecycle transitions: ACTIVE -> CONFLICTED, CONFLICTED -> ACTIVE (`resolve_conflict`), CONFLICTED -> REVOKED, CONFLICTED -> SUPERSEDED.
  14. `mark_conflicted` validation: rejects marking on or with terminal constraints.
  15. Snapshot deep immutability: `snapshot.constraints` tuple and `snapshot.metadata` FrozenDict reject in-place tampering.
  16. Ledger initialization with iterable of constraints.
  17. Corrupted snapshot duplicate ID rejection.
  18. Top-level package exports.
  19. Agent inference prohibited from HARD authority.
  20. Non-empty ID and name validation.
  21. Constraint model shallow immutability (`frozen=True`).
  22. Deep immutability of nested collections (`paths`, `tools`, `actions`, `conflicts_with` tuples; `metadata`, `selectors` `FrozenDict`; nested dicts/lists).
  23. External reference isolation (mutating inputs before/after creation leaves model unaffected).
  24. Constraint model serialization round-trip preserving `FrozenDict` and tuples.

**Known limitations:**  
- In-memory only for v0.1 (as specified by TASK-001 scope; persistent storage like SQLite/PostgreSQL is deferred to later milestones).
- SpecGuard rules and NL constraint extraction are not included (out of scope per task specification).

**Commit/PR:**  
- Branch: `task/TASK-001-core-ledger`
- Commit SHA: `85f0195`

**Questions/blockers:**  
- None. All CHANGES_REQUESTED items (Python 3.11 compatibility, deep immutability, explicit CONFLICTED lifecycle transitions) have been fully implemented, hardened, and verified across Python 3.11 and 3.12.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED

**Reviewed implementation:** `0ce2fd897ba5e407407586fe67db987b3e182f6d`

**Findings:**

### BLOCKER 1 — Python 3.11 compatibility is broken

The project contract and `pyproject.toml` require Python 3.11+, but `models.py` declares:

```python
type ConstraintId = str
```

PEP 695 `type` alias syntax requires Python 3.12. The executor reported tests only on Python 3.12.9, so the required Python 3.11 acceptance criterion was not actually verified.

**Required fix:**
- Replace the 3.12-only alias syntax with a Python 3.11-compatible typed alias, e.g. `ConstraintId: TypeAlias = str` (or an equivalent well-typed 3.11-compatible definition).
- Add a CI/tox/nox or other reproducible check that exercises Python 3.11. At minimum, the executor must run the full test suite under Python 3.11 and report it.

### BLOCKER 2 — durable models are only shallow-frozen

`ConfigDict(frozen=True)` prevents assignment to model attributes, but nested mutable values remain mutable. Current durable models expose mutable containers such as:
- `ConstraintProvenance.metadata: dict`
- `ConstraintScope.paths/tools/actions: list`
- `ConstraintScope.selectors: dict`
- `ConstraintRelation.conflicts_with: list`
- `ConstraintRelation.metadata: dict`
- `LedgerSnapshot.constraints: list`
- `LedgerSnapshot.metadata: dict`

As a result, callers can mutate data in-place after the constraint has been added to the ledger, e.g. append a path or alter provenance metadata, silently changing historical state. This violates the architecture requirement that provenance/history be preserved and makes future SpecGuard decisions non-auditable.

**Required fix:**
- Make durable nested state structurally immutable or defensively isolated. Prefer immutable field types for durable domain data (e.g. tuples/frozensets and an immutable/validated representation for structured mappings), or implement defensive deep-copy/freeze semantics with tests that prove the ledger's stored history cannot be mutated through an external reference.
- Preserve clean JSON serialization/deserialization.
- Add tests that attempt in-place mutation of scope, provenance metadata, relation metadata/conflict collections, and snapshot data, and prove historical ledger state cannot be changed.

### REQUIRED HARDENING — lifecycle semantics around CONFLICTED

The current implementation treats `CONFLICTED` as neither active nor terminal. Therefore:
- `add()` can accept a pre-conflicted constraint;
- `revoke()` / `supersede()` can transition a conflicted constraint because they reject only terminal states;
- `supersede()` can accept a replacement in `CONFLICTED` state and silently force it to `ACTIVE`.

This is ambiguous state-machine behavior and will matter directly to SpecGuard.

**Required fix:**
- Define the allowed lifecycle transitions explicitly in code/tests.
- New constraints and superseding replacements should normally enter the ledger as `ACTIVE`; reject incompatible pre-set lifecycle states instead of silently normalizing them.
- Decide and document whether `CONFLICTED -> REVOKED/SUPERSEDED` is legal; whichever rule is chosen must be explicit and tested.

**What was good:**
- Domain boundaries are appropriately narrow and vendor-neutral.
- Provenance/source/strength distinctions are well modeled.
- Typed exceptions, supersession lineage, round-trip serialization, and failure-path tests are good foundations.
- No LLM/network/database scope creep was introduced.

**Required re-check before resubmission:**
- Full test suite on Python 3.11 and current development Python.
- New immutability regression tests.
- New lifecycle transition-table tests.
- Update Executor Report with the new commit SHA and exact checks run.

**Next instruction:**
Fix TASK-001 on the same branch `task/TASK-001-core-ledger`. Do not start TASK-002.
