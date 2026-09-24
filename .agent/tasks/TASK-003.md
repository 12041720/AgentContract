# TASK-003 — SpecGuard Pre/Post Action Validation Engine

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-003-specguard`  
**Main-agent review:** second-round changes requested

## Objective

Implement deterministic SpecGuard validation over the accepted Constraint Ledger and Trace model.

TASK-003 should answer:

> Given the currently active constraints and a proposed/observed agent action, should it be ALLOWED, WARNED, or BLOCKED, and why?

This task is deterministic. No LLM calls.

## Required reading

1. `AGENTS.md`
2. `.agent/STATE.md`
3. `docs/ARCHITECTURE.md`
4. `.agent/tasks/TASK-001.md`
5. `.agent/tasks/TASK-002.md`
6. this file

## Scope

Implement under `src/agentcontract/guard/` plus tests.

### Required domain concepts

At minimum define:

- `GuardDecision`
- `DecisionKind`: `ALLOW`, `WARN`, `BLOCK`
- `Action` or equivalent normalized action model
- `ActionKind` at minimum covering generic tool/file/command operations
- matched constraint references
- human-readable reason(s)
- optional trace/provenance pointers

The action model must remain vendor-neutral.

### Required rule semantics

Implement deterministic matching for constraints using existing `ConstraintScope` fields:

- `target_type`
- `paths`
- `tools`
- `actions`
- `selectors`

Minimum v0.1 behavior:

1. Only ACTIVE constraints participate in enforcement.
2. HARD matched prohibition/requirement violations produce `BLOCK`.
3. SOFT matched violations produce `WARN`.
4. ASSUMPTION must never independently block an action.
5. Multiple matched constraints are aggregated deterministically.
6. BLOCK dominates WARN; WARN dominates ALLOW.
7. Every non-ALLOW decision must identify which constraint(s) caused it.
8. Unknown/unmatched constraints must not silently block.

### Pre-action validation

Implement an API equivalent to:

```python
decision = guard.evaluate(action, ledger=ledger)
```

Examples that must be representable:

- path write denied by a hard constraint;
- tool invocation denied by tool scope;
- destructive action denied by action scope;
- soft preference produces warning;
- unrelated constraint does not match.

### Post-action validation

Add a narrow post-action API for validating observed effects/events against constraints.

For v0.1, it is sufficient to support deterministic observations such as:

- actual changed paths;
- actual tool used;
- actual action/effect category.

Do not implement EvidenceGate claim verification here.

### Decision provenance

A `GuardDecision` must retain enough information to answer:

- which action was checked;
- which constraints matched;
- which constraint(s) caused block/warn;
- what deterministic rule triggered;
- optional TracePointer to the proposed/observed event.

Decisions should be serializable and immutable.

## Matching rules

Keep matching explicit and conservative.

Recommended semantics:

- empty scope field means “no restriction on that dimension”;
- populated `paths` match normalized path selectors;
- populated `tools` match exact normalized tool names for v0.1;
- populated `actions` match normalized action kinds;
- `target_type`, when present, must match;
- selectors may support exact key/value matching only for v0.1.

Do not invent regex/glob DSL unless clearly necessary. If supporting path globs, document them and test them carefully.

## Important constraint semantics

TASK-001 models constraints generically and does not yet contain a dedicated “prohibition vs requirement” enum.

For TASK-003, introduce the minimum explicit rule semantics needed for deterministic enforcement. Do not infer prohibition from arbitrary natural-language description text.

A good solution may add a small typed field/model such as:

- rule/effect: `DENY`, `REQUIRE`, `PREFER`

or an equivalent explicit representation.

If this requires an API-preserving extension to the constraint model, keep existing TASK-001 serialization/backward compatibility intact and update tests.

## Out of scope

Do not implement:

- LLM/NL constraint extraction;
- EvidenceGate;
- claim verification;
- shell command semantic parsing beyond normalized input supplied to Action;
- database persistence;
- Codex/Claude/MCP adapters;
- policy DSL;
- automatic remediation/planning.

## Acceptance criteria

- [ ] local Python 3.12.9 only;
- [ ] deterministic action model;
- [ ] immutable serializable GuardDecision;
- [ ] ACTIVE-only enforcement;
- [ ] HARD violation -> BLOCK;
- [ ] SOFT violation -> WARN;
- [ ] ASSUMPTION cannot independently BLOCK;
- [ ] deterministic multi-constraint precedence;
- [ ] path/tool/action/target/selector matching;
- [ ] pre-action API;
- [ ] narrow post-action validation API;
- [ ] decision includes matched constraint IDs and reasons;
- [ ] optional TracePointer provenance supported;
- [ ] TASK-001 and TASK-002 tests remain green;
- [ ] no LLM/network/vendor dependency;
- [ ] full pytest suite passes.

## Required test scenarios

At minimum:

1. hard path prohibition blocks write;
2. soft path preference warns;
3. assumption alone does not block;
4. unrelated constraint -> allow;
5. multiple constraints where BLOCK dominates WARN;
6. revoked/superseded/conflicted constraints are not enforced as ACTIVE;
7. tool-name matching;
8. action-kind matching;
9. target-type matching;
10. selector exact-match behavior;
11. decision contains matched constraint IDs;
12. action/decision serialization round-trip;
13. TracePointer retained in decision;
14. post-action observation detects a hard violation;
15. existing TASK-001/TASK-002 suite remains green.

## Environment / checks

Use only the user's local Python 3.12.9.

```bash
python --version
python -m pytest -v
```

Do not install another Python interpreter for compatibility testing.

## Executor Report

> Execution agent: fill this section only after implementation.

**Implementation summary:**  
- **Environment & Baseline Alignment:** Development and testing executed exclusively on the user's installed local **Python 3.12.9** baseline (`python --version` -> `Python 3.12.9`).
- **Fix Round 1 & Round 2 BLOCKER 1 — Truly Exact Typed Selector Equality (Scalar and Nested):**
  - Updated `_exact_value_equal` in `src/agentcontract/guard/engine.py` to enforce strict type identity (`type(v1) is not type(v2) -> False`).
  - Prohibits int vs float equivalence: `1 != 1.0` (and `1 != "1"`, `True != 1`, `True != "True"`).
  - Recursively compares nested `Mapping` (`FrozenDict`, `dict`) and sequence (`list`, `tuple`) objects element-by-element with the same strict typed rules, preventing nested equivalence (such as `{"retries": 1}` vs `{"retries": 1.0}` or `[1, 2]` vs `[1, 2.0]`).
  - Added extensive test coverage for scalar int-vs-float and nested mapping/sequence typed mismatches in `tests/guard/test_engine.py` (`test_scenario_10_selector_exact_match_behavior`).
- **Fix Round 1 & Round 2 BLOCKER 2 — Explicit compliance_scope Invariant for REQUIRE and PREFER:**
  - In `Constraint._validate_invariants` (`src/agentcontract/constraints/models.py`), enforced that `REQUIRE` and `PREFER` constraints require a non-None `compliance_scope`, raising `ConstraintValidationError` when None.
  - Preserved 100% backward compatibility for pre-TASK-003 constraints: default `rule_effect=RuleEffect.DENY` allows `compliance_scope=None`.
  - In `SpecGuard.evaluate` (`src/agentcontract/guard/engine.py`), updated defensive fallback so any missing `compliance_scope` evaluates to `False` (never silently compliant).
  - Added model validation tests and JSON serialization round-trip tests in `tests/constraints/test_models.py` (`test_require_and_prefer_constraints_require_compliance_scope` and `test_require_and_prefer_serialization_round_trip`).
- **Fix Round 1 BLOCKER 3 — Post-Action Validation of All Observed Effects:**
  - Evaluates all observed runtime effects: `changed_paths` as `FILE_WRITE`, `accessed_paths` as `FILE_READ`, and general tool effects as `TOOL_CALL`, aggregating deterministically with `BLOCK > WARN > ALLOW`.
- **Fix Round 1 BLOCKER 4 — Enforce Deterministic Ordering by Rejecting Unordered Sets:**
  - Rejects `set`/`frozenset` inputs for order-sensitive sequences with `GuardValidationError` (`(GuardError, ValueError)`).
- **Top-Level Exports & Clean Packaging:**
  - Exported guard primitives in `src/agentcontract/__init__.py` and `src/agentcontract/guard/__init__.py`.

**Files changed:**  
- `src/agentcontract/constraints/models.py` (enforced `compliance_scope` requirement for `REQUIRE`/`PREFER` in `_validate_invariants`)
- `src/agentcontract/guard/engine.py` (implemented recursive strict typed equality in `_exact_value_equal`, defensive fallback in `evaluate`)
- `src/agentcontract/guard/exceptions.py` (inherited `GuardValidationError` from `GuardError, ValueError`)
- `src/agentcontract/guard/models.py` (rejected `set`/`frozenset` inputs for order-sensitive sequences)
- `tests/constraints/test_models.py` (added tests for REQUIRE/PREFER compliance_scope invariant and serialization)
- `tests/guard/test_engine.py` (added tests for scalar int-vs-float and nested mapping/sequence typed mismatches)
- `tests/guard/test_models.py` (tests for rejecting unordered set/frozenset inputs across models)
- `.agent/tasks/TASK-003.md` (updated Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **102 passed in 0.75s** (100% pass rate: 35 constraint tests + 41 trace tests + 26 guard tests).
- All 15 required test scenarios verified green, including TASK-001 and TASK-002 suites.

**Known limitations:**  
- Pre/post validation is synchronous for v0.1 in-memory execution; async workflow runtime is scheduled for TASK-007.
- Shell command semantic parsing relies on normalized inputs/operations provided to `Action` rather than full bash AST parsing.

**Commit/PR:**  
- Branch: `task/TASK-003-specguard`
- Fix Commit SHA: `cf80fd4` (Round 2 fixes: exact selector and compliance_scope invariant)

**Questions/blockers:**  
- None. All Round 1 and Round 2 review blockers resolved, verified, and tested on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — ROUND 2 (NARROW SEMANTICS FIX)

**Reviewed branch head:** `9146c0e98e5446762c635252f0bf064e7eea62e9`

**Round-1 fixes verified:**
- REQUIRE/PREFER now distinguish applicability from compliance.
- `Constraint.rule_effect` is the single policy-effect source.
- changed/accessed post-action effects are evaluated separately and aggregated.
- unordered set/frozenset inputs are rejected for order-sensitive fields.
- executor reports 100/100 tests passing on local Python 3.12.9.

### BLOCKER 1 — "exact typed" selector equality is still not exact

Current `_exact_value_equal()` intentionally treats different numeric types as equal:

```python
if type(v1) is not type(v2):
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        return v1 == v2
```

Therefore:

```python
_exact_value_equal(1, 1.0) is True
```

This contradicts the stated exact typed semantics.

The implementation also does not recursively enforce type identity. When two FrozenDict/tuple values have the same outer type, it falls through to Python `==`, so nested values such as `{"x": 1}` and `{"x": 1.0}` can still compare equal.

**Required fix:**
- exact means exact: different durable value types must not compare equal;
- `1 != 1.0`;
- recursively compare FrozenDict/mappings and tuples element-by-element with the same exact typed rule;
- keep bool distinct from int;
- add tests for scalar int-vs-float and nested mapping/tuple typed mismatches.

### BLOCKER 2 — REQUIRE/PREFER without compliance_scope silently become no-op

Current semantics use:

```python
... if c.compliance_scope is not None else True
```

So a malformed:

```python
Constraint(rule_effect=REQUIRE, compliance_scope=None)
```

is always considered compliant. PREFER behaves the same way.

That turns a configuration error into silent ALLOW, which is unsafe and makes rule semantics ambiguous.

**Required fix:**
- enforce at the Constraint model boundary that `REQUIRE` and `PREFER` require a non-None `compliance_scope`;
- `DENY` does not require one;
- keep backward compatibility for pre-TASK-003 constraints because their default effect is DENY;
- add model/serialization tests for this invariant.

### REPORT ACCURACY

The Executor Report lists commit `b9b4c05`, but that SHA is not present on the remote branch. The actual remote branch head containing the fixes is:

```text
9146c0e98e5446762c635252f0bf064e7eea62e9
```

Update the Executor Report with the actual pushed commit SHA on resubmission.

**Required re-check:**
- local Python 3.12.9 only;
- `python --version`;
- `python -m pytest -v`;
- all TASK-001/TASK-002 tests remain green.

**Next instruction:**
Apply these two narrow fixes on `task/TASK-003-specguard`. Do not start TASK-004.

