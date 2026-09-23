# TASK-001 — Core domain model and Constraint Ledger

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-001-core-ledger`  
**Main-agent review:** third-round changes requested

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
  - Resolved Python 3.11 compatibility using `TypeAlias`.
  - Replaced lists with tuples and introduced initial `FrozenDict`.
  - Defined initial `ALLOWED_TRANSITIONS`.
- **Review Fixes — Round 2 (Iteration 3, `b152216`):**
  - **Fixed Blocker 1 (True Immutability via Composition Mapping):**
    - Refactored `FrozenDict` from a `dict` subclass to a `collections.abc.Mapping` implementation using composition (`_data: dict[str, Any]` private backing store).
    - Completely eliminated mutable dict methods (`pop`, `update`, `clear`, `setdefault`, `popitem`) and operators (`|=` raises `TypeError`, `dict.__setitem__` raises `TypeError`).
    - Implemented recursive deep freezing (`_freeze_value`) for nested mappings, lists, and sets.
    - Preserved Pydantic v2 schema generation and JSON serialization round-trips via `__get_pydantic_core_schema__`.
    - Added extensive regression tests covering item assignment, `|=`, base-class dict method inapplicability, absence of mutable operations, nested freezing, and external input isolation.
  - **Fixed Blocker 2 (Unified Lifecycle Transition Enforcement via `validate_transition`):**
    - Established `validate_transition(current, target, constraint_id)` as the single source of truth for lifecycle transitions directly using `ALLOWED_TRANSITIONS`.
    - Updated every status-changing operation in `ConstraintLedger` (`revoke`, `supersede`, `mark_conflicted`, `resolve_conflict`) to validate through `validate_transition`.
    - Enforced that `mark_conflicted()` rejects source constraints that are already `CONFLICTED` (`CONFLICTED -> CONFLICTED` disallowed by `ALLOWED_TRANSITIONS`).
    - Decided, documented, and enforced the rule for `mark_conflicted()`: the conflicting peer constraint named in `conflicts_with` must also be currently in `ACTIVE` status (rejecting terminal or conflicted peers).
    - Added table-driven tests exhaustively enumerating all 16 `(from_status, to_status)` pairs across `ConstraintStatus`, asserting that allowed transitions pass and disallowed transitions explicitly raise `InvalidConstraintTransitionError`.

**Files changed:**  
- `src/agentcontract/constraints/models.py` (updated: `FrozenDict` as composition-based `Mapping`, `_freeze_value`, `ALLOWED_TRANSITIONS`, `validate_transition`)
- `src/agentcontract/constraints/ledger.py` (updated: all lifecycle transitions route through `validate_transition`, peer active precondition in `mark_conflicted`)
- `src/agentcontract/constraints/exceptions.py` (typed domain exceptions)
- `src/agentcontract/constraints/__init__.py` (exported `validate_transition`, `FrozenDict`, `ALLOWED_TRANSITIONS`, and core domain types)
- `src/agentcontract/__init__.py` (root package exports)
- `pyproject.toml` (pytest `pythonpath = ["src"]`)
- `tests/constraints/test_models.py` (updated: added `FrozenDict` true immutability, `|=` rejection, `dict.__setitem__` rejection, absence of mutable methods, nested freezing, external isolation)
- `tests/constraints/test_ledger.py` (updated: table-driven status pair tests for all 16 combinations, peer active precondition tests, snapshot immutability)
- `.agent/tasks/TASK-001.md` (updated Executor Report)

**Tests/checks:**  
- **Python 3.11.12 Check:**
  - Command: `uv run --python 3.11 --with pytest python -m pytest -v`
  - Result: 31 passed in 0.63s (100% pass rate).
- **Python 3.12.9 Check:**
  - Command: `python -m pytest -v`
  - Result: 31 passed in 0.67s (100% pass rate).
- **Test Scenarios (31 tests total):**
  1. Add and retrieve explicit hard user constraint.
  2. Agent assumption distinguishable from user authority in ledger.
  3. Revoke active constraint, check list_active vs get, verify provenance/scope preservation.
  4. Supersede "must use Redis" with "PostgreSQL allowed", verify old record queryable and history links both.
  5. Cannot revoke or supersede terminal constraint (verified via `validate_transition`).
  6. Duplicate ID rejection on add and supersede.
  7. Serialization round-trip (`to_json` -> `from_json`, `to_dict` -> `from_dict`).
  8. Active listing excludes revoked and superseded entries.
  9. Multi-hop supersession lineage traversal (A -> B -> C).
  10. Not found error handling for lookup, revoke, supersede, and history.
  11. Table-driven test for all 16 `(from_status, to_status)` pairs in `ALLOWED_TRANSITIONS`.
  12. `add` rejects non-active initial states (rejects REVOKED, SUPERSEDED, CONFLICTED).
  13. `supersede` rejects non-active replacement states.
  14. `CONFLICTED` lifecycle transitions: ACTIVE -> CONFLICTED, CONFLICTED -> ACTIVE (`resolve_conflict`), CONFLICTED -> REVOKED, CONFLICTED -> SUPERSEDED, and rejection of CONFLICTED -> CONFLICTED.
  15. `mark_conflicted` peer precondition: rejects non-active peers (REVOKED, CONFLICTED) and terminal sources.
  16. Snapshot deep immutability: `constraints` tuple and `metadata` FrozenDict reject in-place tampering (`|=`, `dict.__setitem__`, append).
  17. Ledger initialization with iterable of constraints.
  18. Corrupted snapshot duplicate ID rejection.
  19. Top-level package exports.
  20. Add explicit hard user constraint (models test).
  21. Agent assumption distinguishable from user authority (models test).
  22. Agent inference prohibited from HARD authority.
  23. Non-empty ID and name validation.
  24. Constraint model shallow immutability (`frozen=True`).
  25. FrozenDict item assignment and item deletion prohibited.
  26. FrozenDict in-place union (`|=`) prohibited.
  27. FrozenDict absence and inapplicability of mutable dict operations (`pop`, `update`, `clear`, `setdefault`, `popitem`, `dict.__setitem__`).
  28. FrozenDict recursive nested mapping and list freezing.
  29. FrozenDict external input mutation isolation.
  30. Deep immutability of constraint models (tuples and FrozenDict).
  31. Constraint model serialization round-trip.

**Known limitations:**  
- In-memory only for v0.1 (as specified by TASK-001 scope; persistent storage like SQLite/PostgreSQL is deferred to later milestones).
- SpecGuard rules and NL constraint extraction are not included (out of scope per task specification).

**Commit/PR:**  
- Branch: `task/TASK-001-core-ledger`
- Commit SHA: `b152216`

**Questions/blockers:**  
- None. Both Round 2 blockers (true immutability of FrozenDict without dict inheritance, and unified transition table enforcement with table-driven tests) have been implemented, verified, and pass on Python 3.11 and 3.12.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — ROUND 3 (FINAL HARDENING)

**Reviewed implementation:** `b1522169346945cb22a4be62bcf1cb2c2b0731a8`

**Accepted improvements from this round:**
- `FrozenDict` no longer subclasses `dict`; `|=`, `dict.__setitem__`, and normal mutable-dict methods are no longer valid public mutation paths.
- Nested values are recursively frozen and serialization round-trips are preserved.
- `validate_transition()` is now the central lifecycle enforcement helper.
- `revoke`, `supersede`, `mark_conflicted`, and `resolve_conflict` route status changes through the transition table.
- The full 4x4 lifecycle matrix is covered by table-driven tests.
- `CONFLICTED -> CONFLICTED` is explicitly rejected and conflicting peers must be ACTIVE.

### BLOCKER 1 — FrozenDict still exposes a mutable backing dictionary

The implementation now uses composition, but stores:

```python
self._data: dict[str, Any] = {...}
```

External callers can still mutate durable state directly:

```python
fd = FrozenDict({"a": 1})
fd._data["a"] = 999
```

The same applies through models such as:

```python
constraint.provenance.metadata._data["tampered"] = True
```

This silently alters historical/provenance state after it has been recorded. The underscore naming convention is not an immutability guarantee, and Round 2 explicitly required **no exposed mutable backing store**.

**Required fix:**
- Store the backing mapping itself in an immutable/read-only container, preferably `types.MappingProxyType` over an already deep-frozen private dict, or another composition that cannot be mutated through the exposed attribute.
- Ensure no attribute reachable from the public `FrozenDict` object exposes a mutable collection that can change logical contents.
- Add a regression test proving direct access to the backing attribute cannot mutate contents.

### BLOCKER 2 — public lifecycle transition table is mutable

`ALLOWED_TRANSITIONS` is now the authoritative source of truth, which is good, but it is declared as a normal mutable dictionary and exported publicly:

```python
ALLOWED_TRANSITIONS: dict[...] = {...}
```

External code can therefore rewrite lifecycle semantics at runtime:

```python
ALLOWED_TRANSITIONS[ConstraintStatus.REVOKED] = frozenset({ConstraintStatus.ACTIVE})
```

After that, `validate_transition()` accepts a transition that the domain model intends to forbid.

**Required fix:**
- Make the transition table structurally read-only, e.g. `MappingProxyType` or another immutable mapping.
- Keep each target collection immutable (`frozenset` is already appropriate).
- Add a regression test proving callers cannot alter the state machine at runtime.

**Required re-check before final resubmission:**
- Full suite on Python 3.11 and Python 3.12+.
- Regression test for `FrozenDict` backing-store access.
- Regression test for transition-table mutation.
- Update Executor Report with the new commit SHA and exact checks.

**Next instruction:**
Apply these two narrow hardening fixes on `task/TASK-001-core-ledger`. Do not start TASK-002. If these fixes pass review, TASK-001 is expected to be accepted and merged.

