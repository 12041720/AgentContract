# TASK-003 — SpecGuard Pre/Post Action Validation Engine

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-003-specguard`  
**Main-agent review:** changes requested

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
- **Fix BLOCKER 1 — REQUIRE / PREFER Semantics with Explicit Applicability vs Compliance Scopes:**
  - Removed duplicate `rule_effect` override from `ConstraintScope`. `Constraint.rule_effect` is the single authoritative source of policy semantics (`DENY`, `REQUIRE`, `PREFER`).
  - Added `compliance_scope: ConstraintScope | None = None` to `Constraint`.
  - In `SpecGuard.evaluate`:
    - `DENY`: If applicability `scope` matches -> violation (`BLOCK` if HARD, `WARN` if SOFT or ASSUMPTION).
    - `REQUIRE`: If applicability `scope` matches:
      - If `compliance_scope` matches -> compliant, no violation.
      - If `compliance_scope` does not match -> violation (`BLOCK` if HARD, `WARN` if SOFT or ASSUMPTION).
    - `PREFER`: If applicability `scope` matches:
      - If `compliance_scope` matches -> compliant, no warning.
      - If `compliance_scope` does not match -> warning (`WARN`).
    - Non-applicable actions (`scope` does not match) remain allowed and are not evaluated against `compliance_scope`.
    - Purely typed scope and rule-effect matching without any natural language description inference.
- **Fix BLOCKER 2 — True Exact Selector Key/Value Matching:**
  - Replaced stringified comparison (`str(a) == str(b)`) in `match_scope` with typed `_exact_value_equal(v1, v2)`.
  - Enforced strict type preservation: `type(v1) is type(v2)` ensures `1 != "1"`, `True != "True"`, and `True != 1` (bool is not conflated with int).
  - Recursively compares nested collections and handles finite floats / None / bool / int / str.
- **Fix BLOCKER 3 — Post-Action Validation of All Observed Effects:**
  - Refactored `evaluate_post_action` and `evaluate_observation` to evaluate all observed runtime effects rather than selecting only the first non-empty path category.
  - Distinguishes observed writes from observed reads:
    - Every path in `changed_paths` is evaluated as an observed `ActionKind.FILE_WRITE`.
    - Every path in `accessed_paths` is evaluated as an observed `ActionKind.FILE_READ`.
    - Any general tool effect is evaluated as an observed `ActionKind.TOOL_CALL`.
  - Aggregates all sub-decisions deterministically with `BLOCK > WARN > ALLOW`, ensuring mixed observations (e.g., safe write + forbidden read) correctly identify and surface the read violation.
- **Fix BLOCKER 4 — Enforce Deterministic Ordering by Rejecting Unordered Sets:**
  - In `Action._normalize_paths`, `ActionObservation._normalize_paths`, and `GuardDecision._normalize_tuples`, explicitly check for and reject `(set, frozenset)` with `GuardValidationError` (`"must be an ordered sequence (list or tuple), not a set/frozenset"`).
  - Defined `GuardValidationError(GuardError, ValueError)` ensuring standard Pydantic `ValidationError` wrapping during model validation.
  - Prevents nondeterministic path ordering, target path selection, and reason sequencing.
- **Top-Level Exports & Clean Packaging:**
  - Maintained top-level exports in `src/agentcontract/__init__.py` and `src/agentcontract/guard/__init__.py`.
  - Added package markers in `tests/trace/__init__.py` and `tests/guard/__init__.py` to eliminate pytest module naming collisions.

**Files changed:**  
- `src/agentcontract/constraints/models.py` (added `compliance_scope`, simplified single authoritative `rule_effect` on `Constraint`)
- `src/agentcontract/guard/exceptions.py` (inherited `GuardValidationError` from `GuardError, ValueError`)
- `src/agentcontract/guard/models.py` (rejected `set`/`frozenset` inputs for order-sensitive sequences)
- `src/agentcontract/guard/engine.py` (implemented `_exact_value_equal`, fixed REQUIRE/PREFER semantics, validated all post-action observed effects with write/read separation)
- `tests/guard/test_engine.py` (added tests for exact selector type mismatch, mixed post-action read/write violation, REQUIRE/PREFER compliance vs applicability semantics)
- `tests/guard/test_models.py` (added tests for rejecting unordered set/frozenset inputs across models)
- `.agent/tasks/TASK-003.md` (updated Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **100 passed in 0.68s** (100% pass rate: 33 constraint tests + 41 trace tests + 26 guard tests).
- All 15 required test scenarios verified green, including TASK-001 and TASK-002 suites.

**Known limitations:**  
- Pre/post validation is synchronous for v0.1 in-memory execution; async workflow runtime is scheduled for TASK-007.
- Shell command semantic parsing relies on normalized inputs/operations provided to `Action` rather than full bash AST parsing.

**Commit/PR:**  
- Branch: `task/TASK-003-specguard`
- Commit SHA: `b9b4c05` (follow-up commit resolving Round 1 review blockers)

**Questions/blockers:**  
- None. All 4 blockers from Round 1 Main Agent Review are resolved, verified, and tested on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED

**Reviewed implementation:** `033eed532a47a9d735b2ea7e3aa4008e4cb5797d`

**Accepted foundation:**
- Action / ActionObservation / GuardDecision models are a good vendor-neutral base.
- ACTIVE-only enforcement and BLOCK > WARN > ALLOW aggregation are correctly structured.
- HARD/SOFT/ASSUMPTION authority handling for DENY rules is appropriate.
- TracePointer provenance, serialization, tool/action/path matching, and pre/post APIs are in place.
- Executor reports 99/99 tests passing on local Python 3.12.9.

### BLOCKER 1 — REQUIRE / PREFER semantics are inverted

Current behavior treats a matching REQUIRE as a violation and a matching PREFER as a warning:

```text
matches REQUIRE scope -> BLOCK
matches PREFER scope  -> WARN
```

But matching the required/preferred condition means the action is compliant. The current engine therefore punishes actions for satisfying the rule.

A single scope also cannot express both:
- **when** a rule applies; and
- **what** must/preferably be true.

**Required fix:**
Use explicit applicability vs compliance semantics. A recommended narrow design:

```text
Constraint.scope             = applicability / "when"
Constraint.compliance_scope  = required or preferred condition
Constraint.rule_effect       = DENY | REQUIRE | PREFER
```

Semantics:

- `DENY`: if applicability scope matches -> violation.
- `REQUIRE`: if applicability matches **and compliance_scope does not match** -> violation.
- `REQUIRE`: if compliance_scope matches -> compliant, no violation.
- `PREFER`: if applicability matches **and preferred/compliance scope does not match** -> WARN.
- `PREFER`: if preferred condition matches -> no warning.

Use an equivalent typed design if cleaner, but do not infer compliance from description text.

Keep one authoritative `rule_effect` location. The newly-added `ConstraintScope.rule_effect` override mixes selector data with policy semantics and should be removed unless there is a concrete need for two independent effect sources.

Add tests demonstrating both compliant and violating REQUIRE/PREFER cases.

### BLOCKER 2 — selector "exact match" is not exact

Current code compares:

```python
str(action_value).strip() == str(selector_value).strip()
```

This makes different typed values equivalent, for example `1` and `"1"`, or `True` and `"True"`.

TASK-003 requires exact key/value matching.

**Required fix:**
- Compare normalized durable values directly, preserving type semantics.
- `1 != "1"`, `True != "True"`.
- Add regression tests for typed mismatches.

### BLOCKER 3 — post-action validation can silently discard observed effects

Current code selects:

```python
changed_paths or accessed_paths or action.paths
```

If both `changed_paths` and `accessed_paths` are present, one entire class of observed effects is discarded.

Example:
- safe file changed;
- forbidden secret file read;
- because `changed_paths` is non-empty, the forbidden read is never evaluated.

**Required fix:**
- Validate all observed effects, not only the first non-empty category.
- Preserve action/effect semantics sufficiently to distinguish writes from reads.
- Recommended: evaluate changed paths as FILE_WRITE observations and accessed paths as FILE_READ observations, plus any explicit observed action/tool effect, then aggregate decisions deterministically with BLOCK > WARN > ALLOW.
- Add a regression test where a safe write and forbidden read occur in the same observation; result must detect the read violation.

### BLOCKER 4 — unordered inputs undermine deterministic decisions

`Action.paths`, `ActionObservation` paths, and `GuardDecision` ID/reason tuple validators currently accept `set/frozenset` and convert iteration order directly to tuple.

That can make target_path selection, reasons, and serialized decisions nondeterministic across runs.

**Required fix:**
- For order-sensitive fields, reject unordered set/frozenset inputs, or normalize them with an explicitly documented deterministic ordering.
- Prefer rejecting sets for paths/reasons and using ordered sequences.
- Add regression tests.

**Required re-check:**
- local Python 3.12.9 only;
- `python --version`;
- `python -m pytest -v`;
- existing TASK-001 and TASK-002 tests remain green;
- update Executor Report with exact result and commit SHA.

**Next instruction:**
Fix these issues on `task/TASK-003-specguard`. Do not start TASK-004.

