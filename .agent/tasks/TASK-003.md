# TASK-003 — SpecGuard Pre/Post Action Validation Engine

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-003-specguard`  
**Main-agent review:** pending

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
Do not start TASK-004 until this section says ACCEPTED.
